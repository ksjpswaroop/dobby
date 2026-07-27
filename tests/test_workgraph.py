"""
The Work Graph.

The rules that matter: the graph is derived on read so it cannot drift from
the five tables behind it, a decided decision leaves the graph, and every
insight is a fact about edges rather than a phrase from a model.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_wg_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog  # noqa: E402
from src.main import app  # noqa: E402
from src.services import decision_service, planning_service  # noqa: E402
from src.services import workgraph_service as svc  # noqa: E402

PROJECT = "default-project"


@pytest.fixture
def proj(db):
    """A project of this test's own.

    Every test module sets DOBBY_DB_PATH at import time but `src.main` is
    imported once, so the whole suite shares one database. Asserting about a
    graph in the shared project makes these tests depend on how many features
    other modules happened to create — and the graph deliberately caps how
    many it draws.
    """
    from src.db.schema import Project

    pid = f"wg-{uuid.uuid4().hex[:8]}"
    with db.get_session() as s:
        s.add(Project(id=pid, name="Work graph test"))
        s.commit()
    return pid


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


def a_feature(db, project_id, title, impact=8):
    fid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(FeatureBacklog(
            id=fid, project_id=project_id, title=title, description=f"About {title}",
            category="core", impact_score=impact, effort_score=3, risk_score=2,
            pareto_score=(impact * 0.6) - 0.9 - 0.2, status="backlog"))
        s.commit()
    return fid


class TestStructure:
    def test_graph_has_nodes_and_edges(self, db, proj):
        out = svc.build(db, proj)
        assert "nodes" in out and "edges" in out
        assert out["project"]["id"] == proj

    def test_features_appear_as_project_nodes(self, db, proj):
        fid = a_feature(db, proj, "Verity Evidence Runner")
        out = svc.build(db, proj)
        assert any(n["id"] == f"project:{fid}" for n in out["nodes"])

    def test_open_decision_appears(self, db, proj):
        d = decision_service.create(db, proj, "Graph decision",
                                    options=[{"label": "A"}, {"label": "B"}])
        out = svc.build(db, proj)
        assert any(n["id"] == f"decision:{d['id']}" for n in out["nodes"])

    def test_decided_decision_leaves_the_graph(self, db, proj):
        d = decision_service.create(db, proj, "Will be decided",
                                    options=[{"label": "Only"}])
        decision_service.decide(db, d["id"], d["options"][0]["id"])
        out = svc.build(db, proj)
        # A settled fork is no longer part of "what is in my way".
        assert not any(n["id"] == f"decision:{d['id']}" for n in out["nodes"])

    def test_unknown_project_raises(self, db, proj):
        with pytest.raises(ValueError):
            svc.build(db, "no-such-project")

    def test_large_backlog_is_capped_and_reports_what_it_hid(self, db, proj):
        for i in range(svc.MAX_PROJECT_NODES + 6):
            a_feature(db, proj, f"Bulk feature {i}", impact=3)
        out = svc.build(db, proj)
        assert out["counts"]["project"] <= svc.MAX_PROJECT_NODES
        # Silent truncation would read as "this is everything".
        assert out["hidden_projects"] > 0

    def test_completed_work_is_not_shown(self, db, proj):
        fid = a_feature(db, proj, "Already finished", impact=10)
        planning_service.move_card(db, fid, "done")
        out = svc.build(db, proj)
        assert not any(n["id"] == f"project:{fid}" for n in out["nodes"])


class TestEdges:
    def test_decision_blocking_a_feature_creates_an_edge(self, db, proj):
        fid = a_feature(db, proj, "Blocked by a fork", impact=10)
        d = decision_service.create(db, proj, "The blocking fork",
                                    options=[{"label": "X"}])
        decision_service.link(db, d["id"], "feature", fid)

        out = svc.build(db, proj)
        assert any(e["source"] == f"project:{fid}"
                   and e["target"] == f"decision:{d['id']}"
                   and e["type"] == "blocked_by" for e in out["edges"])

    def test_feature_blocker_creates_an_edge(self, db, proj):
        a = a_feature(db, proj, "Downstream thing", impact=9)
        b = a_feature(db, proj, "Upstream thing", impact=9)
        planning_service.add_blocker(db, proj, a, b)
        out = svc.build(db, proj)
        assert any(e["source"] == f"project:{a}" and e["target"] == f"project:{b}"
                   for e in out["edges"])

    def test_goal_links_to_the_work_pursuing_it(self, db, proj):
        fid = a_feature(db, proj, "Pursues the north star", impact=10)
        obj = planning_service.create_objective(db, proj, "Build the co-founder")
        kr = planning_service.add_key_result(db, obj["id"], "Core flows shipped")
        planning_service.link_feature_to_kr(db, kr["id"], fid)

        out = svc.build(db, proj)
        assert any(e["source"] == f"goal:{obj['id']}"
                   and e["target"] == f"project:{fid}"
                   and e["type"] == "pursues" for e in out["edges"])

    def test_edges_never_point_at_missing_nodes(self, db, proj):
        out = svc.build(db, proj)
        ids = {n["id"] for n in out["nodes"]}
        for e in out["edges"]:
            assert e["source"] in ids, e
            assert e["target"] in ids, e


class TestDerivedNotStored:
    def test_deciding_changes_the_graph_with_no_other_write(self, db, proj):
        fid = a_feature(db, proj, "Released by deciding", impact=10)
        d = decision_service.create(db, proj, "Fork to settle",
                                    options=[{"label": "Chosen"}])
        decision_service.link(db, d["id"], "feature", fid)

        before = svc.build(db, proj)
        assert any(e["target"] == f"decision:{d['id']}" for e in before["edges"])

        decision_service.decide(db, d["id"], d["options"][0]["id"])

        after = svc.build(db, proj)
        # Nothing rebuilt the graph — it is derived, so it simply reflects
        # the new truth on the next read.
        assert not any(e["target"] == f"decision:{d['id']}" for e in after["edges"])


class TestNodeDetail:
    def test_blocked_project_names_its_blocker(self, db, proj):
        fid = a_feature(db, proj, "Wants to know why it is stuck", impact=10)
        d = decision_service.create(db, proj, "Named blocker fork",
                                    options=[{"label": "Y"}])
        decision_service.link(db, d["id"], "feature", fid)

        detail = svc.node_detail(db, proj, f"project:{fid}")
        assert "Named blocker fork" in detail["insight"]
        assert detail["next_action"]["route"] == "/decisions"

    def test_decision_reports_how_much_is_waiting(self, db, proj):
        d = decision_service.create(db, proj, "Holds up two things",
                                    options=[{"label": "Z"}])
        for i in range(2):
            fid = a_feature(db, proj, f"Waiting item {i}", impact=9)
            decision_service.link(db, d["id"], "feature", fid)

        detail = svc.node_detail(db, proj, f"decision:{d['id']}")
        assert "2 pieces of work" in detail["insight"]

    def test_unblocked_project_says_it_is_ready(self, db, proj):
        fid = a_feature(db, proj, "Nothing in the way", impact=7)
        detail = svc.node_detail(db, proj, f"project:{fid}")
        assert "ready" in detail["insight"].lower()

    def test_insight_is_computed_not_generated(self, db, proj):
        fid = a_feature(db, proj, "Computed insight check", impact=6)
        detail = svc.node_detail(db, proj, f"project:{fid}")
        # No model is involved anywhere in this path.
        assert detail["computed"] is True

    def test_unknown_node_raises(self, db, proj):
        with pytest.raises(ValueError):
            svc.node_detail(db, proj, "project:does-not-exist")


class TestRoutes:
    def test_graph_endpoint(self, client, db, proj):
        r = client.get(f"/api/v1/workgraph/{proj}")
        assert r.status_code == 200
        assert "nodes" in r.json() and "counts" in r.json()

    def test_node_detail_endpoint(self, client, db, proj):
        fid = a_feature(db, proj, "Route detail feature", impact=8)
        r = client.get(f"/api/v1/workgraph/{proj}/node/project:{fid}")
        assert r.status_code == 200 and "insight" in r.json()

    def test_unknown_project_404s(self, client):
        assert client.get("/api/v1/workgraph/nope").status_code == 404

    def test_meta_lists_types(self, client):
        body = client.get("/api/v1/workgraph/meta").json()
        assert "decision" in body["node_types"]
        assert "blocked_by" in body["edge_types"]
