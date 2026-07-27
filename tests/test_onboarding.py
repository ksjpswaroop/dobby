"""
First-run onboarding.

The rule that matters: step state is derived from real data, so completing
a step in the app completes it in the checklist — and undoing it uncompletes
it. A stored checklist could disagree with reality; this one can't.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_onboarding_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import idea_service, onboarding_service as svc  # noqa: E402

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


class TestChecklist:
    def test_has_all_four_steps(self, db):
        out = svc.build_checklist(db, PROJECT)
        assert [s["id"] for s in out["steps"]] == ["model", "capture", "triage", "generate"]
        assert out["total"] == 4

    def test_capture_step_flips_when_an_idea_exists(self, db):
        before = svc.build_checklist(db, PROJECT)
        capture_before = next(s for s in before["steps"] if s["id"] == "capture")["done"]

        idea_service.capture(db, PROJECT, "onboarding first idea")

        after = svc.build_checklist(db, PROJECT)
        capture_after = next(s for s in after["steps"] if s["id"] == "capture")["done"]
        assert capture_after is True
        if not capture_before:
            assert after["done_count"] > before["done_count"]

    def test_triage_step_flips_after_triaging(self, db):
        idea = idea_service.capture(db, PROJECT, "onboarding triage me")
        idea_service.triage_to_backlog(db, idea["id"])
        out = svc.build_checklist(db, PROJECT)
        assert next(s for s in out["steps"] if s["id"] == "triage")["done"] is True

    def test_done_count_matches_done_steps(self, db):
        out = svc.build_checklist(db, PROJECT)
        assert out["done_count"] == sum(1 for s in out["steps"] if s["done"])

    def test_complete_flag_agrees_with_counts(self, db):
        out = svc.build_checklist(db, PROJECT)
        assert out["complete"] == (out["done_count"] == out["total"])


class TestDismiss:
    def test_dismiss_round_trips(self, db):
        svc.set_dismissed(True)
        assert svc.build_checklist(db, PROJECT)["dismissed"] is True
        svc.set_dismissed(False)
        assert svc.build_checklist(db, PROJECT)["dismissed"] is False


class TestRoutes:
    def test_checklist_via_api(self, client):
        resp = client.get(f"/api/v1/projects/{PROJECT}/onboarding")
        assert resp.status_code == 200
        assert len(resp.json()["steps"]) == 4

    def test_dismiss_via_api(self, client):
        resp = client.post("/api/v1/onboarding/dismiss", params={"dismissed": True})
        assert resp.status_code == 200
        assert resp.json()["dismissed"] is True
        client.post("/api/v1/onboarding/dismiss", params={"dismissed": False})
