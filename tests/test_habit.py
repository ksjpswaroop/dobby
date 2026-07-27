"""
Habit, delight & retention.

The rules that matter: quiet hours must wrap midnight correctly, a category
must not fire twice in a day, and a badge must be derived from real state so
it can never be awarded by a drifting counter.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_habit_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import Node, Project  # noqa: E402
from src.main import app  # noqa: E402
from src.services import habit_service as svc  # noqa: E402
from src.services import idea_service  # noqa: E402

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


@pytest.fixture
def clean_settings(monkeypatch):
    """A predictable settings object — the real one is a user file."""
    class S:
        notifications_enabled = True
        quiet_hours_start = 22
        quiet_hours_end = 8
        muted_notifications: list = []
        notification_last_sent: dict = {}
        focus_minutes = 25
        break_minutes = 5

    monkeypatch.setattr("src.settings.get_settings", lambda: S())
    return S


class TestQuietHours:
    def test_window_wrapping_midnight(self):
        # 22:00 -> 08:00 is the interesting case: a naive start <= h < end
        # would call this window empty.
        assert svc.in_quiet_hours(23, 22, 8) is True
        assert svc.in_quiet_hours(2, 22, 8) is True
        assert svc.in_quiet_hours(7, 22, 8) is True
        assert svc.in_quiet_hours(9, 22, 8) is False
        assert svc.in_quiet_hours(21, 22, 8) is False

    def test_same_day_window(self):
        assert svc.in_quiet_hours(13, 12, 14) is True
        assert svc.in_quiet_hours(15, 12, 14) is False

    def test_equal_bounds_means_never_quiet(self):
        assert svc.in_quiet_hours(3, 9, 9) is False


class TestNotificationGate:
    def test_allows_outside_quiet_hours(self, clean_settings):
        out = svc.should_notify("daily_reminder", datetime(2026, 7, 27, 10, 0))
        assert out["allowed"] is True

    def test_blocks_during_quiet_hours(self, clean_settings):
        out = svc.should_notify("daily_reminder", datetime(2026, 7, 27, 23, 30))
        assert out["allowed"] is False
        assert "Quiet hours" in out["reason"]

    def test_blocks_a_muted_category(self, monkeypatch):
        class S:
            notifications_enabled = True
            quiet_hours_start, quiet_hours_end = 22, 8
            muted_notifications = ["achievement"]
            notification_last_sent: dict = {}

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        assert svc.should_notify("achievement", datetime(2026, 7, 27, 10, 0))["allowed"] is False

    def test_blocks_when_globally_disabled(self, monkeypatch):
        class S:
            notifications_enabled = False
            quiet_hours_start, quiet_hours_end = 22, 8
            muted_notifications: list = []
            notification_last_sent: dict = {}

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        assert svc.should_notify("daily_reminder", datetime(2026, 7, 27, 10, 0))["allowed"] is False

    def test_once_per_day_per_category(self, monkeypatch):
        class S:
            notifications_enabled = True
            quiet_hours_start, quiet_hours_end = 22, 8
            muted_notifications: list = []
            notification_last_sent = {"daily_reminder": "2026-07-27T09:00:00"}

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        same_day = svc.should_notify("daily_reminder", datetime(2026, 7, 27, 15, 0))
        next_day = svc.should_notify("daily_reminder", datetime(2026, 7, 28, 9, 0))
        assert same_day["allowed"] is False
        assert next_day["allowed"] is True

    def test_unknown_category_rejected(self, clean_settings):
        with pytest.raises(svc.HabitError):
            svc.should_notify("spam")


class TestReminder:
    def test_message_reflects_real_state(self, db, clean_settings):
        out = svc.daily_reminder(db, PROJECT, datetime(2026, 7, 27, 10, 0))
        assert out["message"]
        assert "allowed" in out

    def test_acknowledges_when_already_active(self, db, clean_settings, monkeypatch):
        monkeypatch.setattr(svc.momentum_service, "get_momentum",
                            lambda *a, **k: {"active_today": True, "streak": 3,
                                             "sparkline": []})
        out = svc.daily_reminder(db, PROJECT, datetime(2026, 7, 27, 10, 0))
        assert "already built" in out["message"]


class TestRecap:
    def test_counts_recent_activity(self, db):
        idea_service.capture(db, PROJECT, "recap idea")
        out = svc.weekly_recap(db, PROJECT)
        assert out["ideas_captured"] >= 1
        assert out["summary"]

    def test_quiet_week_is_encouraging_not_punitive(self, db):
        with db.get_session() as s:
            s.add(Project(id="quiet-proj", name="Quiet"))
            s.commit()
        out = svc.weekly_recap(db, "quiet-proj")
        assert "restart" in out["summary"].lower()


class TestAchievements:
    def test_badges_are_derived_from_state(self, db):
        idea_service.capture(db, PROJECT, "badge trigger")
        out = svc.achievements(db, PROJECT)
        first = next(b for b in out["badges"] if b["slug"] == "first_capture")
        assert first["earned"] is True

    def test_unearned_badges_report_progress(self, db):
        out = svc.achievements(db, PROJECT)
        closer = next(b for b in out["badges"] if b["slug"] == "closer")
        assert 0.0 <= closer["progress"] <= 1.0

    def test_every_badge_is_listed(self, db):
        out = svc.achievements(db, PROJECT)
        assert out["total"] == len(svc.BADGES)

    def test_empty_project_earns_nothing(self, db):
        with db.get_session() as s:
            s.add(Project(id="no-badges", name="Empty"))
            s.commit()
        out = svc.achievements(db, "no-badges")
        assert out["earned_count"] == 0


class TestOnThisDay:
    def test_recent_items_are_not_memories(self, db):
        idea_service.capture(db, PROJECT, "captured just now")
        out = svc.on_this_day(db, PROJECT)
        assert all(m["days_ago"] >= 7 for m in out["memories"])

    def test_finds_a_weekly_anniversary(self, db):
        nid = str(uuid.uuid4())
        with db.get_session() as s:
            s.add(Node(id=nid, project_id=PROJECT, node_type="documentation",
                       title="Old document", content="x",
                       created_at=datetime.utcnow() - timedelta(days=14)))
            s.commit()
        out = svc.on_this_day(db, PROJECT)
        assert any(m["title"] == "Old document" for m in out["memories"])


class TestFocus:
    def test_rejects_absurd_intervals(self):
        with pytest.raises(svc.HabitError):
            svc.set_focus_config(0, 5)
        with pytest.raises(svc.HabitError):
            svc.set_focus_config(25, 999)


class TestShareCard:
    def test_generates_valid_svg(self, db):
        out = svc.share_card(db, PROJECT)
        assert out["svg"].startswith("<svg")
        assert "</svg>" in out["svg"]
        assert out["headline"]

    def test_card_states_what_it_shares(self, db):
        # The card leaves the machine, so its content must be visible in the
        # payload the user can inspect before sharing.
        out = svc.share_card(db, PROJECT)
        assert out["subtitle"]
        assert "Dobby" in out["svg"]


class TestTray:
    def test_summary_shape(self, db):
        out = svc.tray_summary(db, PROJECT)
        assert {"streak", "needs_triage", "running", "clear"} <= set(out)


class TestRoutes:
    def test_meta_lists_badges_and_categories(self, client):
        body = client.get("/api/v1/habit/meta").json()
        assert body["badges"] and "daily_reminder" in body["categories"]

    def test_achievements_endpoint(self, client):
        assert client.get(f"/api/v1/habit/achievements/{PROJECT}").status_code == 200

    def test_recap_endpoint(self, client):
        assert client.get(f"/api/v1/habit/recap/{PROJECT}").status_code == 200

    def test_tray_endpoint(self, client):
        assert client.get(f"/api/v1/habit/tray/{PROJECT}").status_code == 200

    def test_share_card_serves_svg(self, client):
        r = client.get(f"/api/v1/habit/share-card/{PROJECT}.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")

    def test_unknown_notification_category_400s(self, client):
        assert client.get("/api/v1/habit/notifications/nope").status_code == 400

    def test_bad_focus_config_400s(self, client):
        r = client.post("/api/v1/habit/focus",
                        json={"focus_minutes": 0, "break_minutes": 5})
        assert r.status_code == 400
