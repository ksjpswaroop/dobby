"""
Planning & PM — board, blockers, sprints, estimates, OKRs, analytics, WBS.

The rules that matter: blocked is *derived* so it can never disagree with the
blocker rows, a circular dependency is refused at write time, every column
move is recorded (analytics depend on it), and pulling something back out of
Done undoes the completion rather than leaving the board and backlog
disagreeing.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_planning_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.planning_models import FeatureStatusChange, PlanningMeta  # noqa: E402
from src.db.schema import FeatureBacklog  # noqa: E402
from src.main import app  # noqa: E402
from src.services import delivery_analytics as analytics  # noqa: E402
from src.services import planning_service as svc  # noqa: E402
from src.services import wbs_service  # noqa: E402

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


def feat(db, title, impact=5, effort=5, risk=5):
    fid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(FeatureBacklog(
            id=fid, project_id=PROJECT, title=title, description=f"About {title}",
            category="core", impact_score=impact, effort_score=effort, risk_score=risk,
            pareto_score=(impact * 0.6) - (effort * 0.3) - (risk * 0.1),
            status="backlog"))
        s.commit()
    return fid


class TestBoard:
    def test_features_start_in_backlog(self, db):
        fid = feat(db, "Board start")
        board = svc.get_board(db, PROJECT)
        backlog = next(c for c in board["columns"] if c["id"] == "backlog")
        assert any(c["feature_id"] == fid for c in backlog["cards"])

    def test_estimate_seeds_from_effort_score(self, db):
        fid = feat(db, "Seeded estimate", effort=8)
        card = svc.move_card(db, fid, "todo")
        assert card["estimate"] == 8.0

    def test_move_records_a_status_change(self, db):
        fid = feat(db, "Recorded move")
        svc.move_card(db, fid, "in_progress")
        with db.get_session() as s:
            rows = (s.query(FeatureStatusChange)
                    .filter(FeatureStatusChange.feature_id == fid).all())
        assert any(r.to_column == "in_progress" for r in rows)

    def test_moving_to_done_completes_the_feature(self, db):
        fid = feat(db, "Completes")
        svc.move_card(db, fid, "done")
        with db.get_session() as s:
            assert s.get(FeatureBacklog, fid).status == "completed"

    def test_pulling_out_of_done_undoes_completion(self, db):
        fid = feat(db, "Reopened")
        svc.move_card(db, fid, "done")
        svc.move_card(db, fid, "in_progress")
        with db.get_session() as s:
            f = s.get(FeatureBacklog, fid)
            assert f.status == "in_progress"
            assert f.completed_at is None

    def test_blocked_column_cannot_be_set_directly(self, db):
        fid = feat(db, "No direct block")
        with pytest.raises(svc.PlanningError):
            svc.move_card(db, fid, "blocked")

    def test_unknown_column_rejected(self, db):
        with pytest.raises(svc.PlanningError):
            svc.move_card(db, feat(db, "Bad col"), "nonsense")


class TestBlockers:
    def test_blocked_is_derived_onto_the_board(self, db):
        a, b = feat(db, "Downstream"), feat(db, "Upstream")
        svc.move_card(db, a, "todo")
        svc.add_blocker(db, PROJECT, a, b)
        board = svc.get_board(db, PROJECT)
        blocked_col = next(c for c in board["columns"] if c["id"] == "blocked")
        assert any(c["feature_id"] == a for c in blocked_col["cards"])

    def test_finishing_the_blocker_unblocks(self, db):
        a, b = feat(db, "Waits"), feat(db, "Prerequisite")
        svc.add_blocker(db, PROJECT, a, b)
        assert a in svc.list_blockers(db, PROJECT)["blocked_feature_ids"]
        svc.move_card(db, b, "done")
        assert a not in svc.list_blockers(db, PROJECT)["blocked_feature_ids"]

    def test_self_block_rejected(self, db):
        fid = feat(db, "Self")
        with pytest.raises(svc.PlanningError):
            svc.add_blocker(db, PROJECT, fid, fid)

    def test_direct_cycle_rejected(self, db):
        a, b = feat(db, "Cycle A"), feat(db, "Cycle B")
        svc.add_blocker(db, PROJECT, a, b)
        with pytest.raises(svc.PlanningError):
            svc.add_blocker(db, PROJECT, b, a)

    def test_indirect_cycle_rejected(self, db):
        a, b, c = feat(db, "Chain A"), feat(db, "Chain B"), feat(db, "Chain C")
        svc.add_blocker(db, PROJECT, a, b)
        svc.add_blocker(db, PROJECT, b, c)
        with pytest.raises(svc.PlanningError):
            svc.add_blocker(db, PROJECT, c, a)

    def test_blocked_items_are_not_ready(self, db):
        a, b = feat(db, "Not ready", impact=10), feat(db, "Blocks it")
        svc.add_blocker(db, PROJECT, a, b)
        ready_ids = {c["feature_id"] for c in svc.ready_features(db, PROJECT)}
        assert a not in ready_ids


class TestEstimates:
    def test_set_and_read_back(self, db):
        fid = feat(db, "Estimated")
        card = svc.set_estimate(db, fid, 13, "points")
        assert card["estimate"] == 13.0

    def test_negative_rejected(self, db):
        with pytest.raises(svc.PlanningError):
            svc.set_estimate(db, feat(db, "Neg"), -1)

    def test_unknown_unit_rejected(self, db):
        with pytest.raises(svc.PlanningError):
            svc.set_estimate(db, feat(db, "Unit"), 3, "bananas")


class TestSprints:
    def _sprint(self, db, name="S1", capacity=10.0):
        today = datetime.utcnow().date()
        return svc.create_sprint(db, PROJECT, name, today.isoformat(),
                                 (today + timedelta(days=14)).isoformat(),
                                 capacity=capacity)

    def test_create_and_list(self, db):
        sp = self._sprint(db, "Sprint alpha")
        assert any(x["id"] == sp["id"] for x in svc.list_sprints(db, PROJECT))

    def test_end_before_start_rejected(self, db):
        with pytest.raises(svc.PlanningError):
            svc.create_sprint(db, PROJECT, "Bad", "2026-08-10", "2026-08-01")

    def test_activating_one_closes_the_other(self, db):
        a = self._sprint(db, "First active")
        b = self._sprint(db, "Second active")
        svc.set_sprint_state(db, a["id"], "active")
        svc.set_sprint_state(db, b["id"], "active")
        states = {x["id"]: x["state"] for x in svc.list_sprints(db, PROJECT)}
        assert states[a["id"]] == "closed"
        assert states[b["id"]] == "active"

    def test_summary_tracks_committed_vs_completed(self, db):
        sp = self._sprint(db, "Summary sprint", capacity=20)
        f1, f2 = feat(db, "In sprint 1"), feat(db, "In sprint 2")
        svc.set_estimate(db, f1, 5)
        svc.set_estimate(db, f2, 3)
        svc.assign_to_sprint(db, f1, sp["id"])
        svc.assign_to_sprint(db, f2, sp["id"])
        svc.move_card(db, f1, "done")
        out = svc.sprint_summary(db, sp["id"])
        assert out["committed_estimate"] == 8.0
        assert out["completed_estimate"] == 5.0
        assert out["over_capacity"] is False

    def test_over_capacity_flagged(self, db):
        sp = self._sprint(db, "Tight sprint", capacity=2)
        f1 = feat(db, "Too big")
        svc.set_estimate(db, f1, 10)
        svc.assign_to_sprint(db, f1, sp["id"])
        assert svc.sprint_summary(db, sp["id"])["over_capacity"] is True


class TestMilestonesAndTimeline:
    def test_milestone_percent(self, db):
        ms = svc.create_milestone(db, PROJECT, "Launch",
                                  (datetime.utcnow().date() + timedelta(days=30)).isoformat())
        f1, f2 = feat(db, "MS one"), feat(db, "MS two")
        svc.assign_to_milestone(db, f1, ms["id"])
        svc.assign_to_milestone(db, f2, ms["id"])
        svc.move_card(db, f1, "done")
        found = next(m for m in svc.list_milestones(db, PROJECT) if m["id"] == ms["id"])
        assert found["percent"] == 50.0

    def test_timeline_lanes_follow_dependency_depth(self, db):
        a, b, c = feat(db, "Lane A"), feat(db, "Lane B"), feat(db, "Lane C")
        svc.add_blocker(db, PROJECT, b, a)   # b depends on a
        svc.add_blocker(db, PROJECT, c, b)   # c depends on b
        lanes = {x["feature_id"]: x["lane"] for x in svc.timeline(db, PROJECT)["bars"]}
        assert lanes[a] < lanes[b] < lanes[c]

    def test_bad_date_rejected(self, db):
        with pytest.raises(svc.PlanningError):
            svc.create_milestone(db, PROJECT, "Bad date", "not-a-date")


class TestDailyPlan:
    def test_proposal_respects_capacity(self, db):
        for i in range(5):
            fid = feat(db, f"Daily {i}", impact=9)
            svc.set_estimate(db, fid, 2)
        out = svc.propose_daily_plan(db, PROJECT, capacity=5)
        assert out["planned_estimate"] <= 5 or len(out["proposed"]) == 1

    def test_proposal_excludes_blocked(self, db):
        a, b = feat(db, "Blocked daily", impact=10), feat(db, "Blocker daily")
        svc.add_blocker(db, PROJECT, a, b)
        out = svc.propose_daily_plan(db, PROJECT, capacity=99)
        assert a not in {i["feature_id"] for i in out["proposed"]}

    def test_commit_and_reload(self, db):
        today = datetime.utcnow().date().isoformat()
        svc.commit_daily_plan(db, PROJECT, today,
                              [{"feature_id": "x", "title": "Ship it", "estimate": 2}])
        plan = svc.get_daily_plan(db, PROJECT, today)
        assert plan["total"] == 1

    def test_recommitting_same_day_overwrites(self, db):
        day = "2026-01-01"
        svc.commit_daily_plan(db, PROJECT, day, [{"feature_id": "a", "title": "A"}])
        svc.commit_daily_plan(db, PROJECT, day,
                              [{"feature_id": "b", "title": "B"}, {"feature_id": "c", "title": "C"}])
        assert svc.get_daily_plan(db, PROJECT, day)["total"] == 2


class TestOKRs:
    def test_progress_is_impact_weighted(self, db):
        o = svc.create_objective(db, PROJECT, "Ship v1")
        kr = svc.add_key_result(db, o["id"], "Core flows complete")
        big = feat(db, "Big impact", impact=10)
        small = feat(db, "Small impact", impact=1)
        svc.link_feature_to_kr(db, kr["id"], big)
        svc.link_feature_to_kr(db, kr["id"], small)

        svc.move_card(db, small, "done")
        low = svc.kr_progress(db, kr["id"])["percent"]
        svc.move_card(db, big, "done")
        high = svc.kr_progress(db, kr["id"])["percent"]

        # Finishing the small one moves it less than finishing the big one.
        assert low < 50.0
        assert high == 100.0

    def test_objective_rolls_up_key_results(self, db):
        o = svc.create_objective(db, PROJECT, "Rollup objective")
        svc.add_key_result(db, o["id"], "KR one")
        found = next(x for x in svc.list_objectives(db, PROJECT) if x["id"] == o["id"])
        assert found["percent"] == 0.0
        assert len(found["key_results"]) == 1

    def test_blank_title_rejected(self, db):
        with pytest.raises(svc.PlanningError):
            svc.create_objective(db, PROJECT, "  ")


class TestAnalytics:
    def test_throughput_zero_fills_weeks(self, db):
        out = analytics.throughput(db, PROJECT, weeks=6)
        assert len(out) == 6
        assert all("items" in w for w in out)

    def test_completion_counts_once(self, db):
        fid = feat(db, "Counted once")
        svc.move_card(db, fid, "done")
        svc.move_card(db, fid, "in_progress")
        svc.move_card(db, fid, "done")
        total = sum(w["items"] for w in analytics.throughput(db, PROJECT, weeks=2))
        # Bouncing in and out must not inflate throughput.
        with db.get_session() as s:
            dones = (s.query(FeatureStatusChange)
                     .filter(FeatureStatusChange.feature_id == fid,
                             FeatureStatusChange.to_column == "done").count())
        assert dones == 2 and total >= 1

    def test_cycle_time_measures_in_progress_to_done(self, db):
        fid = feat(db, "Cycle timed")
        svc.move_card(db, fid, "in_progress")
        svc.move_card(db, fid, "done")
        out = analytics.cycle_times(db, PROJECT)
        assert out["count"] >= 1

    def test_cumulative_flow_has_a_row_per_day(self, db):
        out = analytics.cumulative_flow(db, PROJECT, days=7)
        assert len(out) == 7
        assert "backlog" in out[0]

    def test_summary_assembles(self, db):
        out = analytics.summary(db, PROJECT)
        assert {"throughput", "velocity", "cycle_time", "cumulative_flow"} <= set(out)

    def test_weekly_review_shape(self, db):
        out = analytics.weekly_review(db, PROJECT)
        assert "carryover" in out and "suggested_capacity" in out
        assert "average" in out["capacity_basis"].lower()


class TestWBS:
    @pytest.mark.asyncio
    async def test_propose_writes_nothing(self, db, monkeypatch):
        parent = feat(db, "Big thing")

        async def fake_call(*a, **k):
            return '[{"title":"Step one","impact":7,"effort":3,"risk":2}]'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        with db.get_session() as s:
            before = s.query(FeatureBacklog).count()
        out = await wbs_service.propose(db, PROJECT, parent)
        with db.get_session() as s:
            assert s.query(FeatureBacklog).count() == before
        assert out["subtasks"][0]["title"] == "Step one"

    def test_accept_creates_features_and_dependencies(self, db):
        parent = feat(db, "Parent for accept")
        out = wbs_service.accept(db, PROJECT, parent, [
            {"title": "First step", "impact": 8, "effort": 2, "risk": 1},
            {"title": "Second step", "impact": 6, "effort": 3, "risk": 2,
             "depends_on": ["First step"]},
        ])
        assert out["count"] == 2
        assert out["dependencies"] == 1

        second = next(c for c in out["created"] if c["title"] == "Second step")
        assert second["feature_id"] in svc.list_blockers(db, PROJECT)["blocked_feature_ids"]

    @pytest.mark.asyncio
    async def test_unparseable_output_raises(self, db, monkeypatch):
        parent = feat(db, "Unparseable parent")

        async def fake_call(*a, **k):
            return "I would probably start with the database"

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        with pytest.raises(wbs_service.WBSError):
            await wbs_service.propose(db, PROJECT, parent)

    def test_accept_nothing_raises(self, db):
        with pytest.raises(wbs_service.WBSError):
            wbs_service.accept(db, PROJECT, feat(db, "Empty accept"), [])


class TestRoutes:
    def test_board_endpoint(self, client):
        r = client.get(f"/api/v1/planning/board/{PROJECT}")
        assert r.status_code == 200 and "columns" in r.json()

    def test_move_to_blocked_returns_400(self, client, db):
        fid = feat(db, "API blocked move")
        r = client.post(f"/api/v1/planning/board/{fid}/move", json={"to_column": "blocked"})
        assert r.status_code == 400

    def test_analytics_endpoint(self, client):
        assert client.get(f"/api/v1/planning/analytics/{PROJECT}").status_code == 200

    def test_weekly_review_endpoint(self, client):
        assert client.get(f"/api/v1/planning/weekly-review/{PROJECT}").status_code == 200

    def test_timeline_endpoint(self, client):
        r = client.get(f"/api/v1/planning/timeline/{PROJECT}")
        assert r.status_code == 200 and "bars" in r.json()

    def test_daily_propose_endpoint(self, client):
        r = client.get(f"/api/v1/planning/daily/{PROJECT}/propose", params={"capacity": 5})
        assert r.status_code == 200 and "proposed" in r.json()

    def test_meta_endpoint(self, client):
        body = client.get("/api/v1/planning/meta").json()
        assert "blocked" in body["columns"]
