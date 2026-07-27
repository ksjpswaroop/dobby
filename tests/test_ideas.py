"""
Idea capture and triage.

The rule that matters: capturing an idea must be as close to friction-free as
`create_ask` already is, and triage must promote into something the rest of
the app understands (a backlog feature, a research brief) without losing the
original capture — status changes, the row never disappears.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_ideas_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog  # noqa: E402
from src.main import app  # noqa: E402
from src.services import idea_service as svc  # noqa: E402

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


class TestCapture:
    def test_captures_with_just_text(self, db):
        idea = svc.capture(db, PROJECT, "what if quick-capture had a hotkey")
        assert idea["status"] == "inbox"
        assert idea["text"] == "what if quick-capture had a hotkey"

    def test_blank_text_rejected(self, db):
        with pytest.raises(svc.IdeaError):
            svc.capture(db, PROJECT, "   ")

    def test_unknown_project_rejected(self, db):
        with pytest.raises(svc.IdeaError):
            svc.capture(db, "no-such-project", "an idea")

    def test_lists_newest_first(self, db):
        svc.capture(db, PROJECT, "first")
        second = svc.capture(db, PROJECT, "second")
        ideas = svc.list_ideas(db, PROJECT)
        assert ideas[0]["id"] == second["id"]

    def test_status_filter_rejects_unknown_status(self, db):
        with pytest.raises(svc.IdeaError):
            svc.list_ideas(db, PROJECT, status="not-a-status")


class TestTriage:
    def test_backlog_triage_creates_feature_and_updates_idea(self, db):
        idea = svc.capture(db, PROJECT, "a feature worth building")
        out = svc.triage_to_backlog(db, idea["id"], impact_score=8, effort_score=3, risk_score=2)
        assert out["status"] == "backlog"
        assert out["promoted_feature_id"]

        with db.get_session() as s:
            feature = s.get(FeatureBacklog, out["promoted_feature_id"])
            assert feature is not None
            assert feature.title.startswith("a feature worth building")
            assert feature.pareto_score == pytest.approx((8 * 0.6) - (3 * 0.3) - (2 * 0.1))

    def test_research_triage_creates_brief_and_updates_idea(self, db):
        idea = svc.capture(db, PROJECT, "is this technically feasible")
        out = svc.triage_to_research(db, idea["id"])
        assert out["status"] == "research"
        assert out["promoted_brief_id"]

    def test_archive_marks_status_without_deleting(self, db):
        idea = svc.capture(db, PROJECT, "not now")
        out = svc.archive(db, idea["id"])
        assert out["status"] == "archived"
        assert svc.get(db, idea["id"]) is not None

    def test_triage_unknown_idea_raises(self, db):
        with pytest.raises(svc.IdeaError):
            svc.triage_to_backlog(db, "no-such-idea")


class TestPinning:
    def test_pin_then_unpin(self, db):
        idea = svc.capture(db, PROJECT, "pin me")
        pinned = svc.set_pinned(db, idea["id"], True)
        assert pinned["pinned"] is True
        unpinned = svc.set_pinned(db, idea["id"], False)
        assert unpinned["pinned"] is False

    def test_pinned_ideas_sort_first(self, db):
        svc.capture(db, PROJECT, "not pinned")
        pin_me = svc.capture(db, PROJECT, "pin sort check")
        svc.set_pinned(db, pin_me["id"], True)
        ideas = svc.list_ideas(db, PROJECT)
        assert ideas[0]["id"] == pin_me["id"]


class TestDelete:
    def test_delete_removes_it(self, db):
        idea = svc.capture(db, PROJECT, "delete me")
        assert svc.delete(db, idea["id"]) is True
        assert svc.get(db, idea["id"]) is None

    def test_delete_unknown_returns_false(self, db):
        assert svc.delete(db, "no-such-idea") is False


class TestRoutes:
    def test_capture_via_api(self, client):
        resp = client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": "via api"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "inbox"

    def test_capture_blank_returns_422(self, client):
        resp = client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": ""})
        assert resp.status_code == 422

    def test_list_via_api(self, client):
        client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": "listed via api"})
        resp = client.get(f"/api/v1/ideas/project/{PROJECT}")
        assert resp.status_code == 200
        assert any(i["text"] == "listed via api" for i in resp.json()["ideas"])

    def test_triage_backlog_via_api(self, client):
        created = client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": "api backlog"}).json()
        resp = client.post(f"/api/v1/ideas/{created['id']}/triage/backlog",
                           json={"impact_score": 9, "effort_score": 2, "risk_score": 1})
        assert resp.status_code == 200
        assert resp.json()["status"] == "backlog"

    def test_unknown_idea_404s(self, client):
        resp = client.get("/api/v1/ideas/no-such-idea")
        assert resp.status_code == 404

    def test_delete_via_api(self, client):
        created = client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": "api delete"}).json()
        resp = client.delete(f"/api/v1/ideas/{created['id']}")
        assert resp.status_code == 200
        assert client.get(f"/api/v1/ideas/{created['id']}").status_code == 404
