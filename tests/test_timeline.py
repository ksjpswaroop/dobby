"""
Activity Timeline.

The rules that matter: newest-first with a stable tie-break (so pagination
never skips or repeats an event), and a category filter that actually
narrows the feed rather than silently ignoring it.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_timeline_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.research_models import ResearchBrief  # noqa: E402
from src.db.run_models import Run  # noqa: E402
from src.db.schema import FeatureBacklog  # noqa: E402
from src.main import app  # noqa: E402
from src.services import idea_service, timeline_service as svc  # noqa: E402

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


def _seed(db):
    now = datetime.utcnow()
    idea_service.capture(db, PROJECT, "an idea for the timeline")
    with db.get_session() as s:
        s.add(FeatureBacklog(
            id=str(uuid.uuid4()), project_id=PROJECT, title="Timeline feature",
            description="d", category="core", impact_score=5, effort_score=5, risk_score=5,
            pareto_score=1.0, status="backlog", created_at=now - timedelta(minutes=5),
        ))
        s.add(Run(
            id=str(uuid.uuid4()), project_id=PROJECT, kind="yolo", label="Timeline run",
            status="ok", started_at=now - timedelta(minutes=10), finished_at=now - timedelta(minutes=8),
        ))
        s.add(ResearchBrief(
            id=str(uuid.uuid4()), project_id=PROJECT, topic="Timeline research",
            status="complete", created_at=now - timedelta(minutes=15), updated_at=now - timedelta(minutes=14),
        ))
        s.commit()


class TestTimeline:
    def test_aggregates_all_categories(self, db):
        _seed(db)
        out = svc.list_events(db, PROJECT, limit=100)
        cats = {e["category"] for e in out["events"]}
        assert cats == set(svc.CATEGORIES)

    def test_sorted_newest_first(self, db):
        out = svc.list_events(db, PROJECT, limit=100)
        timestamps = [e["timestamp"] for e in out["events"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_category_filter_narrows_results(self, db):
        out = svc.list_events(db, PROJECT, category="idea", limit=100)
        assert out["events"]
        assert all(e["category"] == "idea" for e in out["events"])

    def test_run_started_and_finished_both_present(self, db):
        out = svc.list_events(db, PROJECT, category="run", limit=100)
        types = {e["type"] for e in out["events"]}
        assert "run_started_yolo" in types
        assert "run_ok" in types

    def test_pagination_cursor_has_no_overlap(self, db):
        page1 = svc.list_events(db, PROJECT, limit=2)
        assert page1["next_cursor"]
        page2 = svc.list_events(db, PROJECT, cursor=page1["next_cursor"], limit=2)
        ids1 = {e["id"] for e in page1["events"]}
        ids2 = {e["id"] for e in page2["events"]}
        assert not (ids1 & ids2)

    def test_idea_capture_and_triage_both_appear(self, db):
        idea = idea_service.capture(db, PROJECT, "triaged for timeline test")
        idea_service.triage_to_backlog(db, idea["id"])
        out = svc.list_events(db, PROJECT, category="idea", limit=200)
        types = [e["type"] for e in out["events"] if idea["id"] in e["id"]]
        assert "idea_captured" in types
        assert "idea_triaged_backlog" in types


class TestRoutes:
    def test_timeline_via_api(self, client, db):
        resp = client.get(f"/api/v1/timeline/project/{PROJECT}")
        assert resp.status_code == 200
        assert "events" in resp.json()

    def test_meta_lists_categories(self, client):
        resp = client.get("/api/v1/timeline/meta")
        assert resp.status_code == 200
        assert "idea" in resp.json()["categories"]
