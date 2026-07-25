"""
Mind-map service and API tests.

Focus is on the structural rules that keep a tree a tree: cycle prevention,
cascading deletes, and deep copies. These are the failure modes that corrupt a
map silently, so they're covered before the cosmetic paths.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_mm_test_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import Project  # noqa: E402
from src.main import app  # noqa: E402
from src.services import mindmap_service as svc  # noqa: E402

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


@pytest.fixture
def a_map(db):
    """A fresh map with a root node."""
    return svc.create_map(db, PROJECT, "Test map")


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------
class TestMaps:
    def test_create_map_makes_a_root(self, db, a_map):
        assert a_map["root_node_id"], "a new map should start with a root node"
        tree = svc.get_map_tree(db, a_map["id"])
        assert len(tree["nodes"]) == 1
        assert tree["nodes"][0]["title"] == "Test map"

    def test_list_and_get(self, db, a_map):
        assert any(m["id"] == a_map["id"] for m in svc.list_maps(db, PROJECT))
        assert svc.get_map(db, a_map["id"])["title"] == "Test map"

    def test_rename(self, db, a_map):
        svc.update_map(db, a_map["id"], title="Renamed")
        assert svc.get_map(db, a_map["id"])["title"] == "Renamed"

    def test_delete_removes_nodes_but_not_the_project(self, db, a_map):
        svc.create_node(db, a_map["id"], "Child", a_map["root_node_id"])
        assert svc.delete_map(db, a_map["id"]) is True
        assert svc.get_map(db, a_map["id"]) is None
        with db.get_session() as s:
            assert s.get(Project, PROJECT) is not None, "deleting a map must not touch the project"

    def test_duplicate_is_a_deep_copy(self, db, a_map):
        child = svc.create_node(db, a_map["id"], "Child", a_map["root_node_id"])
        svc.create_node(db, a_map["id"], "Grandchild", child["id"])

        copy = svc.duplicate_map(db, a_map["id"])
        assert copy["id"] != a_map["id"]

        orig_tree = svc.get_map_tree(db, a_map["id"])
        copy_tree = svc.get_map_tree(db, copy["id"])
        assert len(copy_tree["flat"]) == len(orig_tree["flat"]) == 3
        # new identities, same shape
        assert not {n["id"] for n in copy_tree["flat"]} & {n["id"] for n in orig_tree["flat"]}
        titles = sorted(n["title"] for n in copy_tree["flat"])
        assert titles == sorted(n["title"] for n in orig_tree["flat"])


# ---------------------------------------------------------------------------
# Nodes & hierarchy
# ---------------------------------------------------------------------------
class TestNodes:
    def test_create_child_and_tree_nesting(self, db, a_map):
        child = svc.create_node(db, a_map["id"], "Child", a_map["root_node_id"])
        svc.create_node(db, a_map["id"], "Grandchild", child["id"])

        tree = svc.get_map_tree(db, a_map["id"])
        root = tree["nodes"][0]
        assert root["children"][0]["title"] == "Child"
        assert root["children"][0]["children"][0]["title"] == "Grandchild"

    def test_update_merges_metadata(self, db, a_map):
        n = svc.create_node(db, a_map["id"], "N", a_map["root_node_id"],
                            metadata={"position": {"x": 1, "y": 2}})
        svc.update_node(db, n["id"], metadata={"priority": 3})
        updated = svc.get_map_tree(db, a_map["id"])
        node = next(x for x in updated["flat"] if x["id"] == n["id"])
        # a position update must not wipe priority, and vice versa
        assert node["metadata"]["position"] == {"x": 1, "y": 2}
        assert node["metadata"]["priority"] == 3

    def test_move_reparents(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        b = svc.create_node(db, a_map["id"], "B", a_map["root_node_id"])
        svc.move_node(db, b["id"], a["id"])
        tree = svc.get_map_tree(db, a_map["id"])
        node_b = next(n for n in tree["flat"] if n["id"] == b["id"])
        assert node_b["parent_id"] == a["id"]

    def test_move_into_own_descendant_is_rejected(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        b = svc.create_node(db, a_map["id"], "B", a["id"])
        c = svc.create_node(db, a_map["id"], "C", b["id"])
        with pytest.raises(svc.MindMapError, match="cycle"):
            svc.move_node(db, a["id"], c["id"])

    def test_move_onto_itself_is_rejected(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        with pytest.raises(svc.MindMapError, match="cycle"):
            svc.move_node(db, a["id"], a["id"])

    def test_delete_removes_descendants(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        svc.create_node(db, a_map["id"], "B", a["id"])
        svc.create_node(db, a_map["id"], "C", a["id"])
        assert svc.delete_node(db, a["id"]) == 3  # A + 2 children
        tree = svc.get_map_tree(db, a_map["id"])
        assert len(tree["flat"]) == 1  # only the root survives

    def test_duplicate_node_copies_subtree(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        svc.create_node(db, a_map["id"], "B", a["id"])
        copy = svc.duplicate_node(db, a["id"])
        assert copy["title"] == "A (copy)"
        tree = svc.get_map_tree(db, a_map["id"])
        assert len(tree["flat"]) == 5  # root + A + B + copy + copy's child


# ---------------------------------------------------------------------------
# Edges, snapshots, validation
# ---------------------------------------------------------------------------
class TestEdgesAndValidation:
    def test_cross_branch_edge_roundtrip(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        b = svc.create_node(db, a_map["id"], "B", a_map["root_node_id"])
        edge = svc.create_edge(db, a_map["id"], a["id"], b["id"])
        assert svc.get_map_tree(db, a_map["id"])["edges"][0]["id"] == edge["id"]
        assert svc.delete_edge(db, edge["id"]) is True
        assert svc.get_map_tree(db, a_map["id"])["edges"] == []

    def test_self_edge_rejected(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        with pytest.raises(svc.MindMapError):
            svc.create_edge(db, a_map["id"], a["id"], a["id"])

    def test_deleting_node_removes_its_edges(self, db, a_map):
        a = svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        b = svc.create_node(db, a_map["id"], "B", a_map["root_node_id"])
        svc.create_edge(db, a_map["id"], a["id"], b["id"])
        svc.delete_node(db, a["id"])
        assert svc.get_map_tree(db, a_map["id"])["edges"] == []

    def test_snapshots(self, db, a_map):
        svc.save_snapshot(db, a_map["id"], {"nodes": []}, "before edit")
        snaps = svc.list_snapshots(db, a_map["id"])
        assert snaps and snaps[0]["label"] == "before edit"

    def test_validate_clean_tree(self, db, a_map):
        svc.create_node(db, a_map["id"], "A", a_map["root_node_id"])
        assert svc.validate_tree(db, a_map["id"]) == []


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------
class TestMindMapAPI:
    def test_full_flow_over_http(self, client):
        m = client.post("/api/v1/mindmaps",
                        json={"project_id": PROJECT, "title": "API map"}).json()
        root = m["root_node_id"]

        child = client.post(f"/api/v1/mindmaps/map/{m['id']}/nodes",
                            json={"title": "Child", "parent_id": root,
                                  "node_type": "Feature"}).json()

        tree = client.get(f"/api/v1/mindmaps/map/{m['id']}/tree").json()
        assert tree["nodes"][0]["children"][0]["title"] == "Child"

        patched = client.patch(f"/api/v1/mindmaps/nodes/{child['id']}",
                               json={"title": "Renamed"}).json()
        assert patched["title"] == "Renamed"

        assert client.delete(f"/api/v1/mindmaps/map/{m['id']}").status_code == 200

    def test_cycle_move_returns_400_not_500(self, client):
        """The canvas relies on 400 to revert its optimistic move."""
        m = client.post("/api/v1/mindmaps",
                        json={"project_id": PROJECT, "title": "Cycle map"}).json()
        a = client.post(f"/api/v1/mindmaps/map/{m['id']}/nodes",
                        json={"title": "A", "parent_id": m["root_node_id"]}).json()
        b = client.post(f"/api/v1/mindmaps/map/{m['id']}/nodes",
                        json={"title": "B", "parent_id": a["id"]}).json()

        r = client.put(f"/api/v1/mindmaps/nodes/{a['id']}/move",
                       json={"new_parent_id": b["id"]})
        assert r.status_code == 400
        assert "cycle" in r.json()["detail"].lower()

    def test_missing_map_404s(self, client):
        assert client.get("/api/v1/mindmaps/map/nope/tree").status_code == 404

    def test_node_types_exposed(self, client):
        types = client.get("/api/v1/mindmaps/types").json()["node_types"]
        assert "Idea" in types and len(types) == 9
