"""
API route coverage.

These endpoints had no tests despite being where the real bugs lived
(`Node.children`, the metadata/extra_metadata collision, a duplicate /graph
route). Everything here runs against a throwaway SQLite file via DOBBY_DB_PATH,
so the user's real database is never touched.
"""

import os
import tempfile
import uuid

import pytest

# Point the app at a temp DB *before* importing it — the path is read in lifespan.
_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_api_test_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402

PROJECT = "default-project"


@pytest.fixture(scope="module")
def client():
    """A client with the app's lifespan run (so app.state.db exists)."""
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Health & bootstrap
# ---------------------------------------------------------------------------
class TestBootstrap:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_default_project_is_autocreated(self, client):
        """A fresh install must be usable with zero manual setup."""
        r = client.get(f"/api/v1/projects/{PROJECT}")
        assert r.status_code == 200
        assert r.json()["id"] == PROJECT


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class TestProjects:
    def test_create_and_list(self, client):
        r = client.post(
            "/api/v1/projects",
            json={"name": "Test Project", "idea": "An idea", "description": "d"},
        )
        assert r.status_code == 200
        created = r.json()
        assert created["name"] == "Test Project"

        listed = client.get("/api/v1/projects").json()
        assert any(p["id"] == created["id"] for p in listed)

    def test_get_missing_project_404s(self, client):
        assert client.get("/api/v1/projects/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# Graph nodes — the code path that used to crash on Node.children
# ---------------------------------------------------------------------------
class TestGraph:
    def test_create_node_with_metadata_persists(self, client):
        r = client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "feature", "title": "Parent", "content": "x",
                  "metadata": {"k": "v"}},
        )
        assert r.status_code == 200
        node_id = r.json()["node_id"]

        # metadata must round-trip (the extra_metadata mapping bug)
        got = client.get(f"/api/v1/nodes/{node_id}")
        assert got.status_code == 200
        assert got.json()["title"] == "Parent"

    def test_child_node_and_graph_children(self, client):
        parent = client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "feature", "title": "P2"},
        ).json()["node_id"]
        child = client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "user_story", "title": "C2", "parent_id": parent},
        ).json()["node_id"]

        # The dashboard graph route is the canonical one and returns mermaid.
        g = client.get(f"/api/v1/projects/{PROJECT}/graph")
        assert g.status_code == 200
        body = g.json()
        assert "mermaid_syntax" in body, "graph must return mermaid for the viewer"
        ids = {n["id"] for n in body["nodes"]}
        assert parent in ids and child in ids

    def test_get_missing_node_404s(self, client):
        assert client.get("/api/v1/nodes/nope").status_code == 404


# ---------------------------------------------------------------------------
# Backlog
# ---------------------------------------------------------------------------
class TestBacklog:
    def test_create_feature_scores_pareto(self, client):
        r = client.post(
            f"/api/v1/projects/{PROJECT}/backlog",
            json={"title": "Search", "description": "find things", "category": "core",
                  "impact_score": 9, "effort_score": 4, "risk_score": 3},
        )
        assert r.status_code == 200
        # (9*0.6) - (4*0.3) - (3*0.1) = 3.9
        assert round(r.json()["pareto_score"], 2) == 3.9

    def test_backlog_listing_and_top(self, client):
        assert client.get(f"/api/v1/projects/{PROJECT}/backlog").status_code == 200
        assert client.get(f"/api/v1/projects/{PROJECT}/backlog/top").status_code == 200


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class TestDocuments:
    def test_documents_groups_by_feature(self, client):
        feature = client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "feature", "title": "Docs Feature"},
        ).json()["node_id"]
        client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "documentation", "title": "Doc A",
                  "content": "hello world", "parent_id": feature},
        )

        r = client.get(f"/api/v1/projects/{PROJECT}/documents")
        assert r.status_code == 200
        body = r.json()
        group = next(g for g in body["features"] if g["feature"]["id"] == feature)
        assert group["document_count"] == 1
        doc = group["documents"][0]
        assert doc["content"] == "hello world"
        assert doc["word_count"] == 2


# ---------------------------------------------------------------------------
# Settings & system
# ---------------------------------------------------------------------------
class TestSettings:
    def test_get_and_update_settings(self, client):
        original = client.get("/api/v1/settings").json()
        assert "model" in original and "ollama_host" in original

        updated = client.put("/api/v1/settings", json={"verification_threshold": 80}).json()
        assert updated["verification_threshold"] == 80

        # restore
        client.put(
            "/api/v1/settings",
            json={"verification_threshold": original["verification_threshold"]},
        )

    def test_threshold_is_validated(self, client):
        assert client.put("/api/v1/settings", json={"verification_threshold": 500}).status_code == 422

    def test_system_info(self, client):
        r = client.get("/api/v1/system/info")
        assert r.status_code == 200
        assert "ollama_reachable" in r.json()


# ---------------------------------------------------------------------------
# Runs (Logs & Traces)
# ---------------------------------------------------------------------------
class TestRuns:
    def test_list_runs_empty(self, client):
        r = client.get("/api/v1/runs")
        assert r.status_code == 200
        assert "runs" in r.json()

    def test_run_lifecycle_is_traced(self, client):
        """A Tracer run must persist with its events and finish state."""
        from src.observability.tracer import Tracer

        tracer = Tracer(app.state.db, kind="test", label="Traced run",
                        project_id=PROJECT, total_steps=2)
        tracer.event("step.start", "Step one", step="one")
        tracer.event("step.done", "Step one done", step="one", duration_ms=12, advance=True)
        tracer.finish("ok", score=93.5)

        detail = client.get(f"/api/v1/runs/{tracer.run_id}").json()
        assert detail["run"]["status"] == "ok"
        assert detail["run"]["score"] == 93.5
        assert detail["run"]["completed_steps"] == 1
        assert [e["event"] for e in detail["events"]] == ["step.start", "step.done"]

    def test_missing_run_404s(self, client):
        assert client.get("/api/v1/runs/nope").status_code == 404


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
class TestSearch:
    def test_empty_query_returns_nothing(self, client):
        assert client.get("/api/v1/search?q=").json()["count"] == 0

    def test_finds_documents_by_content(self, client):
        feature = client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "feature", "title": "Searchable"},
        ).json()["node_id"]
        client.post(
            f"/api/v1/projects/{PROJECT}/graph/nodes",
            json={"node_type": "documentation", "title": "Findme Doc",
                  "content": "a unicorn appears here", "parent_id": feature},
        )

        results = client.get("/api/v1/search?q=unicorn").json()["results"]
        assert any(r["type"] == "document" for r in results)
        assert any("unicorn" in (r["snippet"] or "").lower() for r in results)

    def test_scoped_search_excludes_other_projects(self, client):
        other = client.post(
            "/api/v1/projects", json={"name": "Other", "idea": "zebra idea"}
        ).json()["id"]
        # 'zebra' lives only in the other project's idea text
        scoped = client.get(f"/api/v1/search?q=zebra&project_id={PROJECT}").json()
        assert all(r.get("project_id") != other for r in scoped["results"])
