"""
Decisions — the forks work waits behind.

The rules that matter: an open decision must remove blocked work from the
ready set exactly like an unfinished blocker does, deciding must be
append-only so history survives changing your mind, and a decided decision
must stop blocking anything.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_decisions_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.decision_models import Decision, DecisionOption  # noqa: E402
from src.db.schema import FeatureBacklog, Node  # noqa: E402
from src.main import app  # noqa: E402
from src.services import decision_service as svc  # noqa: E402
from src.services import nba_service, planning_service  # noqa: E402

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


def a_feature(db, title="Blocked work", impact=9):
    fid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(FeatureBacklog(
            id=fid, project_id=PROJECT, title=title, description="d",
            category="core", impact_score=impact, effort_score=2, risk_score=1,
            pareto_score=(impact * 0.6) - 0.6 - 0.1, status="backlog"))
        s.commit()
    return fid


def a_decision(db, title="RAG vs. Structured Reasoning", due_on=None):
    return svc.create(db, PROJECT, title,
                      question="Which approach for the evidence runner MVP?",
                      due_on=due_on,
                      options=[{"label": "RAG", "note": "Faster to build"},
                               {"label": "Structured reasoning",
                                "note": "Higher confidence"}])


class TestCreate:
    def test_creates_with_options(self, db):
        d = a_decision(db)
        assert d["status"] == "open"
        assert [o["label"] for o in d["options"]] == ["RAG", "Structured reasoning"]

    def test_blank_title_rejected(self, db):
        with pytest.raises(svc.DecisionError):
            svc.create(db, PROJECT, "   ")

    def test_bad_date_rejected(self, db):
        with pytest.raises(svc.DecisionError):
            svc.create(db, PROJECT, "Bad date", due_on="next tuesday")

    def test_unknown_project_rejected(self, db):
        with pytest.raises(svc.DecisionError):
            svc.create(db, "no-such-project", "Orphan")

    def test_a_decision_with_no_due_date_is_valid(self, db):
        # Plenty of real decisions have no deadline; inventing one would make
        # the overdue signal meaningless.
        d = svc.create(db, PROJECT, "Undated fork")
        assert d["due_on"] is None
        assert d["overdue"] is False


class TestDueDates:
    def test_past_due_is_overdue(self, db):
        past = (datetime.utcnow() - timedelta(days=2)).date().isoformat()
        d = a_decision(db, "Overdue one", due_on=past)
        assert d["overdue"] is True
        assert d["due_soon"] is False

    def test_near_future_is_due_soon(self, db):
        soon = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        d = a_decision(db, "Soon one", due_on=soon)
        assert d["due_soon"] is True
        assert d["overdue"] is False

    def test_far_future_is_neither(self, db):
        far = (datetime.utcnow() + timedelta(days=60)).date().isoformat()
        d = a_decision(db, "Far one", due_on=far)
        assert d["overdue"] is False and d["due_soon"] is False

    def test_a_decided_decision_is_never_overdue(self, db):
        past = (datetime.utcnow() - timedelta(days=5)).date().isoformat()
        d = a_decision(db, "Decided late", due_on=past)
        svc.decide(db, d["id"], d["options"][0]["id"], "went with RAG")
        assert svc.get(db, d["id"])["overdue"] is False


class TestDeciding:
    def test_decide_records_choice_and_rationale(self, db):
        d = a_decision(db)
        out = svc.decide(db, d["id"], d["options"][1]["id"], "confidence matters more")
        assert out["status"] == "decided"
        assert out["rationale"] == "confidence matters more"
        chosen = [o for o in out["options"] if o["chosen"]]
        assert len(chosen) == 1 and chosen[0]["label"] == "Structured reasoning"

    def test_rejected_options_are_kept(self, db):
        d = a_decision(db)
        out = svc.decide(db, d["id"], d["options"][0]["id"])
        # "why didn't we do the other thing" must stay answerable.
        assert len(out["options"]) == 2

    def test_cannot_decide_twice(self, db):
        d = a_decision(db)
        svc.decide(db, d["id"], d["options"][0]["id"])
        with pytest.raises(svc.DecisionError):
            svc.decide(db, d["id"], d["options"][1]["id"])

    def test_option_from_another_decision_rejected(self, db):
        a, b = a_decision(db, "First"), a_decision(db, "Second")
        with pytest.raises(svc.DecisionError):
            svc.decide(db, a["id"], b["options"][0]["id"])

    def test_options_cannot_change_after_deciding(self, db):
        d = a_decision(db)
        svc.decide(db, d["id"], d["options"][0]["id"])
        with pytest.raises(svc.DecisionError):
            svc.add_option(db, d["id"], "Third way")


class TestSupersede:
    def test_supersede_preserves_the_original(self, db):
        old = a_decision(db, "Original approach")
        svc.decide(db, old["id"], old["options"][0]["id"], "chose RAG")
        new = svc.supersede(db, old["id"], "Revisited approach",
                            options=[{"label": "Structured reasoning"}])

        old_after = svc.get(db, old["id"])
        assert old_after["status"] == "superseded"
        assert old_after["superseded_by"] == new["id"]
        # History survives disagreeing with it later.
        assert old_after["rationale"] == "chose RAG"

    def test_supersede_carries_the_blocking_links_over(self, db):
        fid = a_feature(db, "Waiting on a fork")
        old = a_decision(db, "First take")
        svc.link(db, old["id"], "feature", fid)
        new = svc.supersede(db, old["id"], "Second take",
                            options=[{"label": "Option A"}])
        assert any(l["entity_id"] == fid for l in new["links"])
        # Still blocked — by the new decision now.
        assert fid in svc.blocked_entity_ids(db, PROJECT)

    def test_cannot_supersede_twice(self, db):
        old = a_decision(db, "Superseded once")
        svc.supersede(db, old["id"], "Replacement")
        with pytest.raises(svc.DecisionError):
            svc.supersede(db, old["id"], "Another replacement")


class TestBlocking:
    def test_open_decision_blocks_a_feature(self, db):
        fid = a_feature(db, "Held up by a fork")
        d = a_decision(db, "Fork holding work")
        svc.link(db, d["id"], "feature", fid)
        assert fid in svc.blocked_entity_ids(db, PROJECT)

    def test_deciding_unblocks_it(self, db):
        fid = a_feature(db, "Released by a decision")
        d = a_decision(db, "Fork to settle")
        svc.link(db, d["id"], "feature", fid)
        svc.decide(db, d["id"], d["options"][0]["id"])
        assert fid not in svc.blocked_entity_ids(db, PROJECT)

    def test_non_blocking_link_does_not_block(self, db):
        fid = a_feature(db, "Merely related")
        d = a_decision(db, "Related but not blocking")
        svc.link(db, d["id"], "feature", fid, blocking=False)
        assert fid not in svc.blocked_entity_ids(db, PROJECT)

    def test_blocked_work_leaves_the_ready_set(self, db):
        fid = a_feature(db, "High value but forked", impact=10)
        assert fid in {c["feature_id"] for c in planning_service.ready_features(db, PROJECT)}

        d = a_decision(db, "Blocks the best work")
        svc.link(db, d["id"], "feature", fid)
        # This is the whole point: a fork nobody has taken blocks progress as
        # hard as an unbuilt prerequisite.
        assert fid not in {c["feature_id"]
                           for c in planning_service.ready_features(db, PROJECT)}

    def test_blockers_for_names_the_decision(self, db):
        fid = a_feature(db, "Wants to know why")
        d = a_decision(db, "The named blocker")
        svc.link(db, d["id"], "feature", fid)
        found = svc.blockers_for(db, PROJECT, "feature", fid)
        assert any(x["title"] == "The named blocker" for x in found)

    def test_link_to_a_missing_feature_rejected(self, db):
        d = a_decision(db)
        with pytest.raises(svc.DecisionError):
            svc.link(db, d["id"], "feature", "no-such-feature")

    def test_unknown_link_type_rejected(self, db):
        d = a_decision(db)
        with pytest.raises(svc.DecisionError):
            svc.link(db, d["id"], "spaceship", "x")

    def test_linking_is_idempotent(self, db):
        fid = a_feature(db)
        d = a_decision(db)
        svc.link(db, d["id"], "feature", fid)
        out = svc.link(db, d["id"], "feature", fid)
        assert len([l for l in out["links"] if l["entity_id"] == fid]) == 1

    def test_unlink_releases_the_work(self, db):
        fid = a_feature(db, "Unlinked later")
        d = a_decision(db)
        out = svc.link(db, d["id"], "feature", fid)
        link_id = next(l["id"] for l in out["links"] if l["entity_id"] == fid)
        svc.unlink(db, link_id)
        assert fid not in svc.blocked_entity_ids(db, PROJECT)


class TestOrdering:
    def test_overdue_sorts_above_due_soon(self, db):
        past = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
        soon = (datetime.utcnow() + timedelta(days=1)).date().isoformat()
        a_decision(db, "Zzz due soon", due_on=soon)
        a_decision(db, "Aaa overdue", due_on=past)
        first = svc.list_decisions(db, PROJECT, status="open")[0]
        assert first["overdue"] is True

    def test_undated_but_blocking_outranks_dated_but_idle(self, db):
        far = (datetime.utcnow() + timedelta(days=90)).date().isoformat()
        svc.create(db, PROJECT, "Dated but blocks nothing", due_on=far)
        blocking = svc.create(db, PROJECT, "Undated but blocks work")
        fid = a_feature(db, "Behind the undated fork")
        svc.link(db, blocking["id"], "feature", fid)

        openish = [d for d in svc.list_decisions(db, PROJECT, status="open")
                   if d["title"] in ("Dated but blocks nothing", "Undated but blocks work")]
        assert openish[0]["title"] == "Undated but blocks work"


class TestSummaryAndNBA:
    def test_summary_counts(self, db):
        out = svc.pending_summary(db, PROJECT)
        assert {"open", "overdue", "due_soon", "blocking_work"} <= set(out)

    def test_overdue_decision_surfaces_in_next_best_action(self, db):
        past = (datetime.utcnow() - timedelta(days=3)).date().isoformat()
        a_decision(db, "Urgent unresolved fork", due_on=past)
        kinds = {s["kind"] for s in nba_service.compute(db, PROJECT)}
        assert "overdue_decision" in kinds

    def test_decision_weight_outranks_a_failed_run(self):
        assert nba_service.WEIGHTS["overdue_decision"] > nba_service.WEIGHTS["failed_run"]


class TestDelete:
    def test_delete_removes_options_and_links(self, db):
        fid = a_feature(db)
        d = a_decision(db, "To be deleted")
        svc.link(db, d["id"], "feature", fid)
        assert svc.delete(db, d["id"]) is True
        assert svc.get(db, d["id"]) is None
        assert fid not in svc.blocked_entity_ids(db, PROJECT)

    def test_delete_unknown_returns_false(self, db):
        assert svc.delete(db, "no-such-decision") is False


class TestRoutes:
    def test_create_and_get(self, client):
        r = client.post("/api/v1/decisions", json={
            "project_id": PROJECT, "title": "API decision",
            "options": [{"label": "A"}, {"label": "B"}]})
        assert r.status_code == 200
        did = r.json()["id"]
        assert client.get(f"/api/v1/decisions/{did}").status_code == 200

    def test_decide_via_api(self, client):
        created = client.post("/api/v1/decisions", json={
            "project_id": PROJECT, "title": "API decide",
            "options": [{"label": "Only option"}]}).json()
        r = client.post(f"/api/v1/decisions/{created['id']}/decide",
                        json={"option_id": created["options"][0]["id"],
                              "rationale": "no alternative"})
        assert r.status_code == 200 and r.json()["status"] == "decided"

    def test_deciding_twice_returns_409(self, client):
        created = client.post("/api/v1/decisions", json={
            "project_id": PROJECT, "title": "API twice",
            "options": [{"label": "X"}]}).json()
        oid = created["options"][0]["id"]
        client.post(f"/api/v1/decisions/{created['id']}/decide", json={"option_id": oid})
        again = client.post(f"/api/v1/decisions/{created['id']}/decide",
                            json={"option_id": oid})
        assert again.status_code == 409

    def test_summary_endpoint(self, client):
        r = client.get(f"/api/v1/decisions/project/{PROJECT}/summary")
        assert r.status_code == 200 and "open" in r.json()

    def test_unknown_decision_404s(self, client):
        assert client.get("/api/v1/decisions/nope").status_code == 404

    def test_meta_lists_states(self, client):
        body = client.get("/api/v1/decisions/meta").json()
        assert "open" in body["states"] and "feature" in body["link_types"]
