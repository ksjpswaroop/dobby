"""
Today Home.

The rule that matters: every section is capped, and `clear` is true only
when nothing is actually waiting on the builder — an empty home screen must
mean "nothing to do", never "the query failed".
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_home_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.run_models import Run  # noqa: E402
from src.db.schema import FeatureBacklog  # noqa: E402
from src.main import app  # noqa: E402
from src.services import home_service as svc, idea_service, inbox_service  # noqa: E402

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


class TestEmptyState:
    def test_clear_when_nothing_waiting(self, db):
        home = svc.build_home(db, PROJECT)
        assert home["clear"] is True
        assert home["needs_decision"] == []
        assert home["needs_triage"] == []

    def test_greeting_always_present(self, db):
        assert svc.build_home(db, PROJECT)["greeting"].startswith("Good ")


class TestSections:
    def test_untriaged_idea_shows_in_needs_triage(self, db):
        idea = idea_service.capture(db, PROJECT, "needs triaging")
        home = svc.build_home(db, PROJECT)
        assert idea["id"] in {i["id"] for i in home["needs_triage"]}
        assert home["clear"] is False

    def test_triaged_idea_leaves_needs_triage(self, db):
        idea = idea_service.capture(db, PROJECT, "will be triaged")
        idea_service.triage_to_backlog(db, idea["id"])
        home = svc.build_home(db, PROJECT)
        assert idea["id"] not in {i["id"] for i in home["needs_triage"]}

    def test_pending_ask_shows_in_needs_decision(self, db):
        ask = inbox_service.create_ask(db, PROJECT, "Approve this?")
        home = svc.build_home(db, PROJECT)
        assert ask["id"] in {a["id"] for a in home["needs_decision"]}

    def test_failed_run_shows_in_needs_attention(self, db):
        run_id = str(uuid.uuid4())
        with db.get_session() as s:
            s.add(Run(id=run_id, project_id=PROJECT, kind="verify",
                      label="A failing run", status="failed"))
            s.commit()
        home = svc.build_home(db, PROJECT)
        assert run_id in {r["id"] for r in home["needs_attention"]}

    def test_top_backlog_sorted_by_pareto(self, db):
        with db.get_session() as s:
            for score in (1.0, 9.0, 5.0):
                s.add(FeatureBacklog(
                    id=str(uuid.uuid4()), project_id=PROJECT, title=f"Feature {score}",
                    description="d", category="core", impact_score=5, effort_score=5,
                    risk_score=5, pareto_score=score, status="backlog",
                ))
            s.commit()
        scores = [f["pareto_score"] for f in svc.build_home(db, PROJECT)["top_backlog"]]
        assert scores == sorted(scores, reverse=True)

    def test_sections_are_capped(self, db):
        for i in range(svc.SECTION_LIMIT + 3):
            idea_service.capture(db, PROJECT, f"overflow idea {i}")
        home = svc.build_home(db, PROJECT)
        assert len(home["needs_triage"]) == svc.SECTION_LIMIT


class TestRoutes:
    def test_home_via_api(self, client):
        resp = client.get(f"/api/v1/projects/{PROJECT}/home")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("greeting", "needs_decision", "needs_triage", "in_progress",
                    "needs_attention", "top_backlog", "clear"):
            assert key in body
