"""
Time-blocked planning.

The rules that matter: the most valuable work lands in the deep-work window
rather than wherever there is room, blocks never run through lunch, buffers
sit between blocks so one overrun does not cascade, and work that will not
fit is reported rather than silently dropped.
"""

import os
import tempfile
import uuid
from datetime import datetime

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_tb_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog, Project  # noqa: E402
from src.main import app  # noqa: E402
from src.services import timeblock_service as svc  # noqa: E402

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
def proj(db):
    pid = f"tb-{uuid.uuid4().hex[:8]}"
    with db.get_session() as s:
        s.add(Project(id=pid, name="Timeblock test"))
        s.commit()
    return pid


def seed_features(db, project_id, n=3):
    """Real backlog work, so an integration test schedules something."""
    with db.get_session() as s:
        for i in range(n):
            s.add(FeatureBacklog(
                id=str(uuid.uuid4()), project_id=project_id, title=f"Seeded {i}",
                description="d", category="core", impact_score=9 - i,
                effort_score=2, risk_score=1,
                pareto_score=(9 - i) * 0.6 - 0.7, status="backlog"))
        s.commit()


def item(title, estimate=2.0, pareto=5.0, fid=None):
    return {"feature_id": fid or str(uuid.uuid4()), "title": title,
            "estimate": estimate, "pareto_score": pareto}


def work_blocks(schedule):
    return [b for b in schedule["blocks"] if b["kind"] != "break"]


class TestDayShape:
    def test_defaults_are_valid(self):
        shape = svc.day_shape()
        assert shape["start"] == "09:00"

    def test_end_before_start_rejected(self):
        with pytest.raises(svc.TimeblockError):
            svc.day_shape({"start": "17:00", "end": "09:00"})

    def test_deep_window_must_sit_inside_the_day(self):
        with pytest.raises(svc.TimeblockError):
            svc.day_shape({"start": "09:00", "end": "17:00",
                           "deep_work_start": "07:00", "deep_work_end": "08:00"})

    def test_malformed_time_rejected(self):
        with pytest.raises(svc.TimeblockError):
            svc.day_shape({"start": "nine o'clock"})

    def test_absurd_buffer_rejected(self):
        with pytest.raises(svc.TimeblockError):
            svc.day_shape({"buffer_minutes": 600})


class TestPlacement:
    def test_highest_value_goes_into_the_deep_window(self):
        out = svc.build_schedule([
            item("Small admin thing", estimate=1, pareto=1.0),
            item("The most valuable thing", estimate=2, pareto=9.5),
        ], plan_date="2026-07-27")
        first = work_blocks(out)[0]
        # Not "whatever was listed first" and not "whatever is smallest".
        assert first["title"] == "The most valuable thing"
        assert first["kind"] == "deep_work"

    def test_deep_work_starts_at_the_window_start(self):
        out = svc.build_schedule([item("Deep thing", estimate=2, pareto=9)],
                                 plan_date="2026-07-27")
        assert work_blocks(out)[0]["start"] == "09:00"

    def test_buffers_sit_between_blocks(self):
        out = svc.build_schedule([
            item("First", estimate=1, pareto=9),
            item("Second", estimate=1, pareto=8),
        ], plan_date="2026-07-27", overrides={"buffer_minutes": 15})
        blocks = work_blocks(out)
        end_first = datetime.strptime(blocks[0]["end"], "%H:%M")
        start_second = datetime.strptime(blocks[1]["start"], "%H:%M")
        gap = (start_second - end_first).total_seconds() / 60
        # One overrun should absorb into the gap, not cascade through the day.
        assert gap >= 15

    def test_zero_buffer_packs_blocks_together(self):
        out = svc.build_schedule([
            item("A", estimate=1, pareto=9), item("B", estimate=1, pareto=8),
        ], plan_date="2026-07-27", overrides={"buffer_minutes": 0})
        blocks = work_blocks(out)
        assert blocks[0]["end"] == blocks[1]["start"]

    def test_nothing_is_scheduled_over_lunch(self):
        out = svc.build_schedule(
            [item(f"Task {i}", estimate=2, pareto=9 - i) for i in range(6)],
            plan_date="2026-07-27")
        lunch_start = datetime.strptime(out["shape"]["lunch_start"], "%H:%M")
        lunch_end = datetime.strptime(out["shape"]["lunch_end"], "%H:%M")
        for b in work_blocks(out):
            start = datetime.strptime(b["start"], "%H:%M")
            end = datetime.strptime(b["end"], "%H:%M")
            assert not (start < lunch_end and end > lunch_start), b

    def test_lunch_appears_as_a_real_block(self):
        out = svc.build_schedule([item("Anything")], plan_date="2026-07-27")
        assert any(b["kind"] == "break" and b["title"] == "Lunch"
                   for b in out["blocks"])

    def test_blocks_come_back_in_clock_order(self):
        out = svc.build_schedule(
            [item(f"Task {i}", estimate=1, pareto=9 - i) for i in range(5)],
            plan_date="2026-07-27")
        starts = [b["start"] for b in out["blocks"]]
        assert starts == sorted(starts)

    def test_work_beyond_the_deep_window_is_scheduled_after_it(self):
        out = svc.build_schedule(
            [item(f"Task {i}", estimate=2, pareto=9 - i * 0.1) for i in range(8)],
            plan_date="2026-07-27")
        kinds = {b["kind"] for b in work_blocks(out)}
        assert "deep_work" in kinds and "admin" in kinds


class TestOverflow:
    def test_work_that_does_not_fit_is_reported_not_dropped(self):
        out = svc.build_schedule(
            [item(f"Task {i}", estimate=3, pareto=9 - i * 0.1) for i in range(12)],
            plan_date="2026-07-27")
        # Silently truncating would read as "this is your whole day".
        assert out["unscheduled"]
        assert out["fits"] is False
        assert all("day is full" in u["reason"] for u in out["unscheduled"])

    def test_a_plan_that_fits_says_so(self):
        out = svc.build_schedule([item("One small thing", estimate=1)],
                                 plan_date="2026-07-27")
        assert out["fits"] is True
        assert out["unscheduled"] == []

    def test_utilisation_is_reported(self):
        out = svc.build_schedule([item("Thing", estimate=2)], plan_date="2026-07-27")
        assert 0 < out["utilisation"] <= 100

    def test_empty_plan_is_valid(self):
        out = svc.build_schedule([], plan_date="2026-07-27")
        assert work_blocks(out) == []
        assert out["fits"] is True


class TestDurations:
    def test_estimate_drives_length(self):
        small = svc.build_schedule([item("Small", estimate=1)], plan_date="2026-07-27")
        big = svc.build_schedule([item("Big", estimate=3)], plan_date="2026-07-27")
        assert work_blocks(big)[0]["minutes"] > work_blocks(small)[0]["minutes"]

    def test_a_tiny_remainder_is_not_padded_up_to_the_floor(self):
        # Deliberate change: the 30-minute floor used to win here. Inflating a
        # few minutes of remaining work into a half-hour block over-books the
        # day with work that does not exist — on precisely the day someone is
        # clearing the last of something.
        out = svc.build_schedule([item("Tiny", estimate=0.1)], plan_date="2026-07-27")
        block = work_blocks(out)[0]
        assert block["minutes"] <= svc.effort.points_to_minutes(0.1)
        assert block["minutes"] > 0

    def test_the_floor_still_applies_to_ordinary_work(self):
        out = svc.build_schedule([item("Normal", estimate=1)], plan_date="2026-07-27")
        assert work_blocks(out)[0]["minutes"] >= svc.DEFAULT_DAY["min_block_minutes"]

    def test_huge_estimates_are_capped(self):
        out = svc.build_schedule([item("Enormous", estimate=99)], plan_date="2026-07-27")
        # An eight-hour unbroken block is not a plan.
        assert work_blocks(out)[0]["minutes"] <= svc.DEFAULT_DAY["max_block_minutes"]

    def test_missing_estimate_still_schedules(self):
        out = svc.build_schedule([{"title": "No estimate", "pareto_score": 5}],
                                 plan_date="2026-07-27")
        assert len(work_blocks(out)) == 1


class TestIntegration:
    def test_plan_day_uses_the_ready_set(self, db, proj):
        seed_features(db, proj)
        out = svc.plan_day(db, proj, capacity=6)
        assert out["ready_count"] >= 3
        assert work_blocks(out)

    def test_blocked_work_never_gets_a_time_slot(self, db, proj):
        from src.services import decision_service

        fid = str(uuid.uuid4())
        with db.get_session() as s:
            s.add(FeatureBacklog(
                id=fid, project_id=proj, title="Behind a fork", description="d",
                category="core", impact_score=10, effort_score=1, risk_score=1,
                pareto_score=5.6, status="backlog"))
            s.commit()

        d = decision_service.create(db, proj, "Blocks the schedule",
                                    options=[{"label": "A"}])
        decision_service.link(db, d["id"], "feature", fid)

        out = svc.plan_day(db, proj, capacity=10)
        # It inherits the ready set's exclusions, so an unresolved fork keeps
        # work off the calendar as well as out of the list.
        assert not any(b.get("feature_id") == fid for b in out["blocks"])

    def test_commit_persists_the_times(self, db, proj):
        from src.services import planning_service

        seed_features(db, proj)
        out = svc.plan_day(db, proj, capacity=4, plan_date="2026-07-27")
        svc.commit_day(db, proj, "2026-07-27", out["blocks"])
        stored = planning_service.get_daily_plan(db, proj, "2026-07-27")
        assert stored and stored["items"]
        assert any(i.get("start") for i in stored["items"])

    def test_commit_excludes_breaks(self, db, proj):
        from src.services import planning_service

        seed_features(db, proj)
        out = svc.plan_day(db, proj, capacity=4, plan_date="2026-07-28")
        svc.commit_day(db, proj, "2026-07-28", out["blocks"])
        stored = planning_service.get_daily_plan(db, proj, "2026-07-28")
        assert stored["items"], "nothing was committed, so the assertion below would be vacuous"
        assert not any(i["title"] == "Lunch" for i in stored["items"])


class TestRoutes:
    def test_meta_exposes_the_default_day(self, client):
        body = client.get("/api/v1/timeblocks/meta").json()
        assert body["default_day"]["start"] == "09:00"
        assert "deep_work" in body["block_kinds"]

    def test_schedule_endpoint(self, client):
        r = client.post("/api/v1/timeblocks/schedule", json={
            "items": [{"title": "Via the API", "estimate": 2, "pareto_score": 8}],
            "plan_date": "2026-07-27"})
        assert r.status_code == 200
        assert r.json()["blocks"]

    def test_bad_shape_400s(self, client):
        r = client.post("/api/v1/timeblocks/schedule", json={
            "items": [], "shape": {"start": "17:00", "end": "09:00"}})
        assert r.status_code == 400

    def test_plan_endpoint(self, client, proj):
        r = client.post(f"/api/v1/timeblocks/plan/{proj}", json={"capacity": 4})
        assert r.status_code == 200 and "blocks" in r.json()
