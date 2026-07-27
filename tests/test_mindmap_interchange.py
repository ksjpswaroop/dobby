"""
Outline interchange against a real database and the HTTP API.

The unit tests in `test_mindmap_outline.py` cover parsing in isolation; this
covers the part that can corrupt data — writing a parsed outline into the tree,
replacing an existing map, and the snapshot that makes that undoable.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_mmx_test_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import mindmap_outline as ol  # noqa: E402
from src.services import mindmap_service as svc  # noqa: E402

PROJECT = "default-project"

OUTLINE = """# Launch plan

## Marketing
Reach the first thousand users.

### Content
- blog posts — two a week
- [x] landing page

## Engineering
### API
### Client
"""


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


class TestImport:
    def test_creates_the_full_hierarchy(self, db):
        result = ol.import_outline(db, PROJECT, OUTLINE)
        assert result["success"]

        tree = svc.get_map_tree(db, result["map_id"])
        assert tree["map"]["title"] == "Launch plan"

        branches = tree["nodes"][0]["children"]
        assert [b["title"] for b in branches] == ["Marketing", "Engineering"]
        assert branches[0]["description"] == "Reach the first thousand users."

        content = branches[0]["children"][0]
        assert content["title"] == "Content"
        assert [c["title"] for c in content["children"]] == ["blog posts", "landing page"]
        assert content["children"][0]["description"] == "two a week"

    def test_checked_state_persists(self, db):
        result = ol.import_outline(db, PROJECT, OUTLINE)
        tree = svc.get_map_tree(db, result["map_id"])
        landing = next(n for n in tree["flat"] if n["title"] == "landing page")
        assert landing["metadata"].get("checked") is True

    def test_round_trips_through_the_database(self, db):
        """import -> export -> import must produce the same shape."""
        first = ol.import_outline(db, PROJECT, OUTLINE)
        exported = ol.to_outline(svc.get_map_tree(db, first["map_id"]))
        second = ol.import_outline(db, PROJECT, exported)

        def shape(map_id):
            def walk(nodes):
                return [(n["title"], walk(n["children"])) for n in nodes]
            return walk(svc.get_map_tree(db, map_id)["nodes"][0]["children"])

        assert shape(first["map_id"]) == shape(second["map_id"])

    def test_an_explicit_title_overrides_the_h1(self, db):
        result = ol.import_outline(db, PROJECT, OUTLINE, title="Renamed")
        assert svc.get_map_tree(db, result["map_id"])["map"]["title"] == "Renamed"


class TestReplace:
    def test_replaces_contents_and_keeps_the_map_id(self, db):
        created = ol.import_outline(db, PROJECT, OUTLINE)
        map_id = created["map_id"]

        ol.replace_from_outline(db, map_id, "# New title\n## Only branch\n")
        tree = svc.get_map_tree(db, map_id)

        assert tree["map"]["title"] == "New title"
        assert [n["title"] for n in tree["nodes"][0]["children"]] == ["Only branch"]
        # The old branches are gone, not orphaned somewhere in the map.
        assert not [n for n in tree["flat"] if n["title"] == "Marketing"]

    def test_snapshots_before_replacing_so_undo_works(self, db):
        created = ol.import_outline(db, PROJECT, OUTLINE)
        map_id = created["map_id"]
        before = len(svc.get_map_tree(db, map_id)["flat"])

        ol.replace_from_outline(db, map_id, "# Wiped\n## Nothing\n")
        snapshots = svc.list_snapshots(db, map_id)
        assert snapshots, "replacing a map must leave a restore point"

        svc.restore_snapshot(db, map_id, snapshots[0]["id"])
        assert len(svc.get_map_tree(db, map_id)["flat"]) == before

    def test_a_bad_outline_changes_nothing(self, db):
        created = ol.import_outline(db, PROJECT, OUTLINE)
        map_id = created["map_id"]
        before = len(svc.get_map_tree(db, map_id)["flat"])

        with pytest.raises(ValueError):
            ol.replace_from_outline(db, map_id, "no structure at all")

        assert len(svc.get_map_tree(db, map_id)["flat"]) == before


class TestApi:
    def test_import_export_endpoints(self, client):
        r = client.post(f"/api/v1/mindmaps/import/{PROJECT}/outline",
                        json={"outline": OUTLINE})
        assert r.status_code == 200, r.text
        map_id = r.json()["map_id"]

        r = client.get(f"/api/v1/mindmaps/map/{map_id}/export/outline")
        assert r.status_code == 200
        assert r.text.startswith("# Launch plan")
        assert "## Marketing" in r.text
        assert "[x] landing page" in r.text

    def test_replace_endpoint(self, client):
        map_id = client.post(f"/api/v1/mindmaps/import/{PROJECT}/outline",
                             json={"outline": OUTLINE}).json()["map_id"]

        r = client.put(f"/api/v1/mindmaps/map/{map_id}/outline",
                       json={"outline": "# Replaced\n## Solo\n"})
        assert r.status_code == 200, r.text
        assert client.get(
            f"/api/v1/mindmaps/map/{map_id}/export/outline").text.startswith("# Replaced")

    def test_invalid_outline_is_a_400_with_guidance(self, client):
        r = client.post(f"/api/v1/mindmaps/import/{PROJECT}/outline",
                        json={"outline": "nothing structured here"})
        assert r.status_code == 400
        assert "#" in r.json()["detail"]

    def test_export_of_a_missing_map_is_404(self, client):
        r = client.get("/api/v1/mindmaps/map/does-not-exist/export/outline")
        assert r.status_code == 404
