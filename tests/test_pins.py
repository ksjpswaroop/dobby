"""
Pins & Favorites.

The rules that matter: pinning is idempotent, unpinning re-flows the
remaining order with no gaps, and a pin whose target was deleted cleans
itself up the next time the list is read rather than showing a broken row.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_pins_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog  # noqa: E402
from src.main import app  # noqa: E402
from src.services import idea_service, pin_service as svc  # noqa: E402

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


def _make_idea(db, text="pin me"):
    return idea_service.capture(db, PROJECT, text)


def _make_feature(db):
    with db.get_session() as s:
        f = FeatureBacklog(
            id=str(uuid.uuid4()), project_id=PROJECT, title="Pinnable feature",
            description="d", category="core", impact_score=5, effort_score=5, risk_score=5,
            pareto_score=1.0, status="backlog",
        )
        s.add(f)
        s.commit()
        return f.id


class TestPin:
    def test_pin_an_idea(self, db):
        idea = _make_idea(db)
        p = svc.pin(db, PROJECT, "idea", idea["id"])
        assert p["entity_type"] == "idea"
        assert p["title"] == "pin me"
        assert p["route"] == "/ideas"

    def test_pin_is_idempotent(self, db):
        idea = _make_idea(db, "idempotent idea")
        first = svc.pin(db, PROJECT, "idea", idea["id"])
        second = svc.pin(db, PROJECT, "idea", idea["id"])
        assert first["id"] == second["id"]
        pins = svc.list_pins(db, PROJECT)
        assert sum(1 for p in pins if p["entity_id"] == idea["id"]) == 1

    def test_pin_unknown_entity_type_rejected(self, db):
        with pytest.raises(svc.PinError):
            svc.pin(db, PROJECT, "not-a-type", "whatever")

    def test_pin_nonexistent_target_rejected(self, db):
        with pytest.raises(svc.PinError):
            svc.pin(db, PROJECT, "idea", "no-such-idea")

    def test_pin_a_feature(self, db):
        feature_id = _make_feature(db)
        p = svc.pin(db, PROJECT, "feature", feature_id)
        assert p["title"] == "Pinnable feature"
        assert p["route"] == "/backlog"


class TestUnpin:
    def test_unpin_removes_and_reflows(self, db):
        i1, i2, i3 = _make_idea(db, "a"), _make_idea(db, "b"), _make_idea(db, "c")
        svc.pin(db, PROJECT, "idea", i1["id"])
        svc.pin(db, PROJECT, "idea", i2["id"])
        svc.pin(db, PROJECT, "idea", i3["id"])
        svc.unpin(db, PROJECT, "idea", i2["id"])
        pins = [p for p in svc.list_pins(db, PROJECT) if p["entity_id"] in (i1["id"], i3["id"])]
        indices = sorted(p["order_index"] for p in svc.list_pins(db, PROJECT))
        assert indices == list(range(len(indices)))
        assert i2["id"] not in {p["entity_id"] for p in svc.list_pins(db, PROJECT)}

    def test_unpin_unknown_returns_false(self, db):
        assert svc.unpin(db, PROJECT, "idea", "no-such-idea") is False


class TestDanglingCleanup:
    def test_deleted_target_is_dropped_on_list(self, db):
        idea = _make_idea(db, "will be deleted")
        svc.pin(db, PROJECT, "idea", idea["id"])
        assert idea["id"] in {p["entity_id"] for p in svc.list_pins(db, PROJECT)}

        idea_service.delete(db, idea["id"])

        pins = svc.list_pins(db, PROJECT)
        assert idea["id"] not in {p["entity_id"] for p in pins}
        # Cleanup also re-flows remaining order indices.
        indices = sorted(p["order_index"] for p in pins)
        assert indices == list(range(len(indices)))


class TestReorder:
    def test_reorder_sets_new_order(self, db):
        # reorder() takes the complete current set of pins (as a real drag
        # would submit the whole reordered list), so build on top of
        # whatever this module-scoped db already has pinned.
        i1, i2 = _make_idea(db, "first"), _make_idea(db, "second")
        p1 = svc.pin(db, PROJECT, "idea", i1["id"])
        p2 = svc.pin(db, PROJECT, "idea", i2["id"])
        current_ids = [p["id"] for p in svc.list_pins(db, PROJECT)]
        new_order = [pid for pid in current_ids if pid not in (p1["id"], p2["id"])] + [p2["id"], p1["id"]]
        reordered = svc.reorder(db, PROJECT, new_order)
        by_id = {p["id"]: p["order_index"] for p in reordered}
        assert by_id[p2["id"]] < by_id[p1["id"]]

    def test_reorder_rejects_mismatched_set(self, db):
        idea = _make_idea(db, "solo")
        p = svc.pin(db, PROJECT, "idea", idea["id"])
        with pytest.raises(svc.PinError):
            svc.reorder(db, PROJECT, [p["id"], "not-a-real-pin-id"])


class TestRoutes:
    def test_pin_via_api(self, client):
        idea = client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": "api pin"}).json()
        resp = client.post("/api/v1/pins", json={
            "project_id": PROJECT, "entity_type": "idea", "entity_id": idea["id"],
        })
        assert resp.status_code == 200
        assert resp.json()["entity_id"] == idea["id"]

    def test_list_via_api(self, client):
        resp = client.get(f"/api/v1/pins/project/{PROJECT}")
        assert resp.status_code == 200
        assert "pins" in resp.json()

    def test_unpin_via_api(self, client):
        idea = client.post("/api/v1/ideas", json={"project_id": PROJECT, "text": "api unpin"}).json()
        client.post("/api/v1/pins", json={
            "project_id": PROJECT, "entity_type": "idea", "entity_id": idea["id"],
        })
        resp = client.delete(f"/api/v1/pins/idea/{idea['id']}", params={"project_id": PROJECT})
        assert resp.status_code == 200
