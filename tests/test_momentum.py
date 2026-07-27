"""
Daily streak & momentum.

Covers the roadmap's six D5 test cases. The pure functions are tested
directly with synthetic events, because the interesting logic is calendar
arithmetic — building real rows at 11:59pm in a specific timezone would test
SQLite, not the boundary rule that actually matters.
"""

import os
import tempfile
import uuid
from datetime import date, datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_momentum_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import idea_service, momentum_service as svc  # noqa: E402

PROJECT = "default-project"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture
def db(client):
    return app.state.db


def ev(iso: str, type_: str = "idea_captured"):
    return {"timestamp": iso, "type": type_}


class TestDayBoundaries:
    def test_utc_timestamp_maps_to_local_day(self):
        # 23:30 UTC is already the next day at +05:30.
        assert svc._local_day("2026-07-27T23:30:00", 330) == date(2026, 7, 28)
        assert svc._local_day("2026-07-27T23:30:00", 0) == date(2026, 7, 27)

    def test_timezone_case_1159pm_and_1201am_are_different_days(self):
        """Roadmap test case 3."""
        before = svc._local_day("2026-07-27T18:29:00", 330)  # 23:59 local
        after = svc._local_day("2026-07-27T18:31:00", 330)   # 00:01 local
        assert before == date(2026, 7, 27)
        assert after == date(2026, 7, 28)
        assert before != after

    def test_negative_offset_rolls_backward(self):
        # 02:00 UTC is still the previous evening at -08:00.
        assert svc._local_day("2026-07-27T02:00:00", -480) == date(2026, 7, 26)


class TestActiveDays:
    def test_same_day_actions_count_once(self):
        """Roadmap test case 2 — no double increment."""
        events = [ev("2026-07-27T09:00:00"), ev("2026-07-27T15:00:00"),
                  ev("2026-07-27T21:00:00")]
        assert svc.active_days(events, 0) == {date(2026, 7, 27)}

    def test_non_qualifying_types_are_ignored(self):
        events = [ev("2026-07-27T09:00:00", "page_viewed")]
        assert svc.active_days(events, 0) == set()

    def test_all_documented_prefixes_qualify(self):
        for t in ("idea_captured", "feature_added", "run_ok", "research_complete"):
            assert svc._qualifies(t), t


class TestStreak:
    def test_consecutive_days_count_up(self):
        """Roadmap test case 1."""
        today = date(2026, 7, 27)
        days = {today, today - timedelta(days=1), today - timedelta(days=2)}
        assert svc.streak_length(days, today) == 3

    def test_gap_resets_streak(self):
        """Roadmap test case 4 — a missed day breaks the run."""
        today = date(2026, 7, 27)
        days = {today, today - timedelta(days=2), today - timedelta(days=3)}
        assert svc.streak_length(days, today) == 1

    def test_yesterday_keeps_streak_alive_before_you_work_today(self):
        today = date(2026, 7, 27)
        days = {today - timedelta(days=1), today - timedelta(days=2)}
        assert svc.streak_length(days, today) == 2

    def test_two_days_idle_breaks_streak(self):
        today = date(2026, 7, 27)
        days = {today - timedelta(days=2), today - timedelta(days=3)}
        assert svc.streak_length(days, today) == 0

    def test_no_activity_is_zero(self):
        """Roadmap test case 6."""
        assert svc.streak_length(set(), date(2026, 7, 27)) == 0


class TestSparkline:
    def test_returns_fourteen_days_oldest_first(self):
        today = date(2026, 7, 27)
        out = svc.sparkline([], 0, today)
        assert len(out) == svc.SPARKLINE_DAYS
        assert out[0]["date"] == (today - timedelta(days=13)).isoformat()
        assert out[-1]["date"] == today.isoformat()

    def test_counts_land_on_the_right_day(self):
        today = date(2026, 7, 27)
        events = [ev("2026-07-27T10:00:00"), ev("2026-07-27T11:00:00"),
                  ev("2026-07-26T10:00:00")]
        by_date = {d["date"]: d["count"] for d in svc.sparkline(events, 0, today)}
        assert by_date["2026-07-27"] == 2
        assert by_date["2026-07-26"] == 1

    def test_idle_days_are_zero_not_missing(self):
        today = date(2026, 7, 27)
        out = svc.sparkline([ev("2026-07-27T10:00:00")], 0, today)
        assert all("count" in d for d in out)
        assert sum(d["count"] for d in out) == 1


class TestLongestRecent:
    def test_finds_best_run(self):
        today = date(2026, 7, 27)
        days = {today - timedelta(days=i) for i in (0, 2, 3, 4, 7)}
        assert svc._longest_recent(days, today) == 3

    def test_empty_is_zero(self):
        assert svc._longest_recent(set(), date(2026, 7, 27)) == 0


class TestIntegration:
    def test_capturing_an_idea_starts_a_streak(self, db):
        """Roadmap test case 5 — computed entirely from local data."""
        idea_service.capture(db, PROJECT, "streak starter")
        out = svc.get_momentum(db, PROJECT, tz_offset_minutes=0)
        assert out["streak"] >= 1
        assert out["active_today"] is True

    def test_sparkline_present_in_payload(self, db):
        out = svc.get_momentum(db, PROJECT, tz_offset_minutes=0)
        assert len(out["sparkline"]) == svc.SPARKLINE_DAYS

    def test_defaults_to_server_timezone_when_offset_omitted(self, db):
        out = svc.get_momentum(db, PROJECT)
        assert "tz_offset_minutes" in out


class TestRoutes:
    def test_momentum_via_api(self, client):
        resp = client.get(f"/api/v1/momentum/project/{PROJECT}")
        assert resp.status_code == 200
        body = resp.json()
        assert "streak" in body and "sparkline" in body

    def test_offset_is_honoured(self, client):
        resp = client.get(f"/api/v1/momentum/project/{PROJECT}",
                          params={"tz_offset_minutes": 330})
        assert resp.status_code == 200
        assert resp.json()["tz_offset_minutes"] == 330
