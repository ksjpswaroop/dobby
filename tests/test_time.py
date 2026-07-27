"""
Time tracking, remaining effort, and the shared capacity unit.

The rules that matter: two clocks must never run at once, a stopped entry is
immutable, the scheduler must place *remaining* time so work visibly shrinks,
and the planner and scheduler must agree on the unit — the disagreement that
left four hours of the day empty.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_time_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog, Project  # noqa: E402
from src.db.time_models import TimeEntry  # noqa: E402
from src.main import app  # noqa: E402
from src.services import effort, planning_service, timeblock_service  # noqa: E402
from src.services import time_service as svc  # noqa: E402


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
    pid = f"tm-{uuid.uuid4().hex[:8]}"
    with db.get_session() as s:
        s.add(Project(id=pid, name="Time test"))
        s.commit()
    return pid


def a_feature(db, proj, title="Tracked work", effort_points=2, impact=8):
    fid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(FeatureBacklog(
            id=fid, project_id=proj, title=title, description="d",
            category="core", impact_score=impact, effort_score=effort_points,
            risk_score=1, pareto_score=impact * 0.6 - effort_points * 0.3 - 0.1,
            status="backlog"))
        s.commit()
    # PlanningMeta seeds its estimate from the effort score on first read.
    planning_service.ready_features(db, proj)
    return fid


class TestEffortConversion:
    def test_points_to_minutes_round_trip(self):
        assert effort.points_to_minutes(2) == 2 * effort.minutes_per_point()
        assert effort.minutes_to_points(90) == round(90 / effort.minutes_per_point(), 2)

    def test_humanise_reads_naturally(self):
        assert effort.humanise(0) == "0m"
        assert effort.humanise(45) == "45m"
        assert effort.humanise(60) == "1h"
        assert effort.humanise(135) == "2h 15m"

    def test_garbage_does_not_crash_the_planner(self):
        assert effort.points_to_minutes(None) > 0
        assert effort.points_to_minutes("nonsense") > 0
        assert effort.humanise(None) == "0m"


class TestTimer:
    def test_start_then_stop_records_the_entry(self, db, proj):
        fid = a_feature(db, proj)
        svc.start(db, proj, fid)
        assert svc.running(db, proj)["feature_id"] == fid
        stopped = svc.stop(db, proj)
        assert stopped["running"] is False
        assert svc.running(db, proj) is None

    def test_running_state_is_derived_not_stored(self, db, proj):
        fid = a_feature(db, proj)
        svc.start(db, proj, fid)
        # No flag anywhere — "am I tracking?" is a query for an open entry.
        with db.get_session() as s:
            open_rows = (s.query(TimeEntry)
                         .filter(TimeEntry.project_id == proj,
                                 TimeEntry.ended_at.is_(None)).count())
        assert open_rows == 1
        svc.stop(db, proj)

    def test_starting_a_second_timer_stops_the_first(self, db, proj):
        a, b = a_feature(db, proj, "First"), a_feature(db, proj, "Second")
        svc.start(db, proj, a)
        out = svc.start(db, proj, b)
        # A log where two things ran at once is a log nobody believes.
        assert out["stopped_previous"] is not None
        assert svc.running(db, proj)["feature_id"] == b
        svc.stop(db, proj)

    def test_stopping_with_nothing_running_returns_none(self, db, proj):
        assert svc.stop(db, proj) is None

    def test_a_forgotten_timer_is_capped_not_discarded(self, db, proj):
        fid = a_feature(db, proj)
        svc.start(db, proj, fid)
        with db.get_session() as s:
            e = (s.query(TimeEntry)
                 .filter(TimeEntry.project_id == proj,
                         TimeEntry.ended_at.is_(None)).first())
            e.started_at = datetime.utcnow() - timedelta(hours=20)
            s.commit()
        stopped = svc.stop(db, proj)
        # The work happened; the duration is fiction.
        assert stopped["minutes"] == svc.MAX_SESSION_MINUTES
        assert "capped" in stopped["note"]

    def test_unknown_feature_rejected(self, db, proj):
        with pytest.raises(svc.TimeError):
            svc.start(db, proj, "no-such-feature")


class TestManualLog:
    def test_log_records_minutes(self, db, proj):
        fid = a_feature(db, proj)
        e = svc.log(db, proj, 90, fid, "worked on the train")
        assert e["minutes"] == 90
        assert e["source"] == "manual"

    def test_zero_or_negative_rejected(self, db, proj):
        with pytest.raises(svc.TimeError):
            svc.log(db, proj, 0)
        with pytest.raises(svc.TimeError):
            svc.log(db, proj, -30)

    def test_absurd_duration_rejected(self, db, proj):
        with pytest.raises(svc.TimeError):
            svc.log(db, proj, 60 * 30)

    def test_time_without_a_feature_is_allowed(self, db, proj):
        # Meetings and admin are real time even when untracked work.
        e = svc.log(db, proj, 30, None, "standup")
        assert e["feature_id"] is None

    def test_delete_is_the_only_correction(self, db, proj):
        fid = a_feature(db, proj)
        e = svc.log(db, proj, 60, fid)
        assert svc.spent_on(db, fid) == 60
        assert svc.delete(db, e["id"]) is True
        assert svc.spent_on(db, fid) == 0


class TestTotals:
    def test_spent_sums_across_entries(self, db, proj):
        fid = a_feature(db, proj)
        svc.log(db, proj, 30, fid)
        svc.log(db, proj, 45, fid)
        assert svc.spent_on(db, fid) == 75

    def test_a_running_timer_counts_toward_spent(self, db, proj):
        fid = a_feature(db, proj)
        svc.start(db, proj, fid)
        with db.get_session() as s:
            e = (s.query(TimeEntry)
                 .filter(TimeEntry.feature_id == fid,
                         TimeEntry.ended_at.is_(None)).first())
            e.started_at = datetime.utcnow() - timedelta(minutes=40)
            s.commit()
        assert svc.spent_on(db, fid) >= 39
        svc.stop(db, proj)

    def test_spent_map_covers_every_feature_in_one_read(self, db, proj):
        a, b = a_feature(db, proj, "A"), a_feature(db, proj, "B")
        svc.log(db, proj, 20, a)
        svc.log(db, proj, 50, b)
        m = svc.spent_map(db, proj)
        assert m[a] == 20 and m[b] == 50

    def test_day_summary_groups_by_feature(self, db, proj):
        fid = a_feature(db, proj, "Summarised")
        svc.log(db, proj, 60, fid)
        svc.log(db, proj, 15, None, "email")
        out = svc.day_summary(db, proj)
        assert out["total_minutes"] == 75
        assert out["untracked_minutes"] == 15
        assert out["by_feature"][0]["minutes"] == 60

    def test_week_summary_zero_fills_gaps(self, db, proj):
        out = svc.week_summary(db, proj, weeks=2)
        assert len(out["days"]) == 14
        assert all("minutes" in d for d in out["days"])

    def test_bad_date_rejected(self, db, proj):
        with pytest.raises(svc.TimeError):
            svc.day_summary(db, proj, "yesterday")


class TestRemainingEffort:
    def test_a_card_reports_spent_and_remaining(self, db, proj):
        fid = a_feature(db, proj, "Half done", effort_points=4)
        estimated = effort.points_to_minutes(4)
        svc.log(db, proj, estimated // 2, fid)

        card = next(c for c in planning_service.ready_features(db, proj)
                    if c["feature_id"] == fid)
        assert card["spent_minutes"] == estimated // 2
        assert card["remaining_minutes"] == estimated - estimated // 2
        assert 45 <= card["percent_spent"] <= 55

    def test_remaining_shrinks_as_time_is_logged(self, db, proj):
        fid = a_feature(db, proj, "Shrinking", effort_points=4)

        def remaining():
            return next(c for c in planning_service.ready_features(db, proj)
                        if c["feature_id"] == fid)["remaining_minutes"]

        before = remaining()
        svc.log(db, proj, 60, fid)
        # The whole point: work visibly gets smaller.
        assert remaining() == before - 60

    def test_over_estimate_is_flagged_not_negative(self, db, proj):
        fid = a_feature(db, proj, "Underestimated", effort_points=1)
        svc.log(db, proj, effort.points_to_minutes(1) + 120, fid)
        card = next(c for c in planning_service.ready_features(db, proj)
                    if c["feature_id"] == fid)
        assert card["over_estimate"] is True
        assert card["remaining_minutes"] == 0

    def test_finished_work_stops_being_proposed(self, db, proj):
        fid = a_feature(db, proj, "All used up", effort_points=1)
        svc.log(db, proj, effort.points_to_minutes(1), fid)
        proposed = planning_service.propose_daily_plan(
            db, proj, capacity_minutes=600)["proposed"]
        # Nothing left to do on it — it needs finishing or re-estimating,
        # not another block of time.
        assert all(p["feature_id"] != fid for p in proposed)


class TestSchedulerUsesRemaining:
    def test_a_block_is_sized_to_what_is_left(self, db, proj):
        out = timeblock_service.build_schedule(
            [{"feature_id": "x", "title": "Mostly done", "estimate": 4,
              "remaining_minutes": 40, "spent_minutes": 140, "pareto_score": 9}],
            plan_date="2026-07-27")
        block = next(b for b in out["blocks"] if b["kind"] != "break")
        assert block["minutes"] == 40
        assert block["partial"] is False

    def test_the_block_explains_work_already_done(self, db, proj):
        out = timeblock_service.build_schedule(
            [{"feature_id": "x", "title": "Continued", "estimate": 6,
              "remaining_minutes": 300, "spent_minutes": 120, "pareto_score": 9}],
            plan_date="2026-07-27")
        block = next(b for b in out["blocks"] if b["kind"] != "break")
        assert "2h" in block["why"]
        assert block["leaves_remaining"] > 0

    def test_a_capped_block_says_what_it_leaves(self, db, proj):
        out = timeblock_service.build_schedule(
            [{"feature_id": "x", "title": "Big", "estimate": 8,
              "remaining_minutes": 400, "spent_minutes": 0, "pareto_score": 9}],
            plan_date="2026-07-27")
        block = next(b for b in out["blocks"] if b["kind"] != "break")
        assert block["partial"] is True
        assert block["leaves_remaining"] == 400 - block["minutes"]

    def test_tomorrow_schedules_less_than_today(self, db, proj):
        fid = a_feature(db, proj, "Two-day job", effort_points=8, impact=10)
        today = timeblock_service.plan_day(db, proj, plan_date="2026-07-27")
        first = next(b for b in today["blocks"] if b.get("feature_id") == fid)

        svc.log(db, proj, first["minutes"], fid)

        tomorrow = timeblock_service.plan_day(db, proj, plan_date="2026-07-28")
        second = next(b for b in tomorrow["blocks"] if b.get("feature_id") == fid)
        # Same estimate, but a day of work happened in between.
        assert second["remaining_minutes"] < first["remaining_minutes"]


class TestCapacityUnits:
    def test_planner_and_scheduler_agree(self, db, proj):
        for i in range(6):
            a_feature(db, proj, f"Item {i}", effort_points=2, impact=9 - i)

        plan = timeblock_service.plan_day(db, proj, plan_date="2026-07-27")
        placed = sum(b["minutes"] for b in plan["blocks"] if b["kind"] != "break")

        # The old bug: capacity in points admitted far less than the day held,
        # leaving hours empty. Utilisation should now be substantial.
        assert plan["utilisation"] > 40, plan["utilisation"]
        assert placed <= plan["capacity_minutes"] + plan["shape"]["max_block_minutes"]

    def test_default_capacity_is_the_workable_day(self, db, proj):
        a_feature(db, proj, "Anything")
        plan = timeblock_service.plan_day(db, proj, plan_date="2026-07-27")
        # 09:00-17:30 minus an hour of lunch minus buffers.
        assert 350 <= plan["capacity_minutes"] <= 460

    def test_points_capacity_still_works_and_is_converted(self, db, proj):
        a_feature(db, proj, "Legacy caller")
        out = planning_service.propose_daily_plan(db, proj, capacity=4)
        assert out["capacity_minutes"] == effort.points_to_minutes(4)

    def test_minutes_capacity_is_respected(self, db, proj):
        for i in range(5):
            a_feature(db, proj, f"Packed {i}", effort_points=2, impact=9 - i)
        out = planning_service.propose_daily_plan(db, proj, capacity_minutes=100)
        assert out["planned_minutes"] <= 100 or len(out["proposed"]) == 1

    def test_legacy_point_fields_still_returned(self, db, proj):
        out = planning_service.propose_daily_plan(db, proj, capacity_minutes=180)
        assert "capacity" in out and "planned_estimate" in out


class TestHonestOverflow:
    def test_work_the_planner_skipped_is_reported(self, db, proj):
        # Each item is bigger than one sitting, so most cannot be started today.
        for i in range(6):
            a_feature(db, proj, f"Large {i}", effort_points=7, impact=9 - i * 0.1)
        out = planning_service.propose_daily_plan(db, proj, capacity_minutes=200)
        # Silently skipping would let the caller report "everything fits".
        assert out["not_today"], "skipped work must be visible"
        assert all("left today" in n["reason"] for n in out["not_today"])

    def test_plan_day_does_not_claim_to_fit_when_it_skipped_work(self, db, proj):
        for i in range(8):
            a_feature(db, proj, f"Big {i}", effort_points=7, impact=9 - i * 0.1)
        plan = timeblock_service.plan_day(db, proj, plan_date="2026-07-27")
        assert plan["not_today"]
        assert plan["fits"] is False

    def test_a_genuinely_light_day_does_fit(self, db, proj):
        a_feature(db, proj, "One small thing", effort_points=1)
        plan = timeblock_service.plan_day(db, proj, plan_date="2026-07-27")
        assert plan["not_today"] == []
        assert plan["fits"] is True

    def test_an_item_claims_at_most_one_sitting(self, db, proj):
        a_feature(db, proj, "Enormous", effort_points=10, impact=10)
        out = planning_service.propose_daily_plan(db, proj, capacity_minutes=600,
                                                  max_per_item_minutes=150)
        first = out["proposed"][0]
        # Letting it claim all ten points of capacity is what left the
        # afternoon empty — the planner booked time the scheduler never placed.
        assert first["today_minutes"] == 150
        assert first["remaining_minutes"] > 150

    def test_the_day_keeps_filling_past_an_item_that_does_not_fit(self, db, proj):
        a_feature(db, proj, "Too big for the gap", effort_points=10, impact=10)
        for i in range(3):
            a_feature(db, proj, f"Small {i}", effort_points=1, impact=5 - i)
        out = planning_service.propose_daily_plan(db, proj, capacity_minutes=200,
                                                  max_per_item_minutes=150)
        titles = [p["title"] for p in out["proposed"]]
        # Breaking at the first misfit used to leave the rest of the day empty.
        assert any(t.startswith("Small") for t in titles), titles


class TestRoutes:
    def test_start_stop_via_api(self, client, db, proj):
        fid = a_feature(db, proj)
        r = client.post("/api/v1/time/start",
                        json={"project_id": proj, "feature_id": fid})
        assert r.status_code == 200 and r.json()["running"] is True
        assert client.post(f"/api/v1/time/stop/{proj}").status_code == 200

    def test_stopping_nothing_409s(self, client, proj):
        assert client.post(f"/api/v1/time/stop/{proj}").status_code == 409

    def test_log_via_api(self, client, db, proj):
        fid = a_feature(db, proj)
        r = client.post("/api/v1/time/log",
                        json={"project_id": proj, "minutes": 45, "feature_id": fid})
        assert r.status_code == 200 and r.json()["human"] == "45m"

    def test_negative_minutes_422s(self, client, proj):
        r = client.post("/api/v1/time/log",
                        json={"project_id": proj, "minutes": -5})
        assert r.status_code == 422

    def test_day_and_week_endpoints(self, client, proj):
        assert client.get(f"/api/v1/time/day/{proj}").status_code == 200
        assert client.get(f"/api/v1/time/weeks/{proj}").status_code == 200

    def test_meta_exposes_the_shared_conversion(self, client):
        body = client.get("/api/v1/time/meta").json()
        assert body["minutes_per_point"] == effort.minutes_per_point()
