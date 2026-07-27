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


# ---------------------------------------------------------------------------
# AI (Phase 2) — the model is mocked so these stay deterministic
# ---------------------------------------------------------------------------
class TestMindMapAI:
    def test_extract_json_handles_fences_and_preamble(self):
        from src.services import mindmap_ai as ai

        assert ai._extract_json('```json\n{"a": 1}\n```') == {"a": 1}
        assert ai._extract_json('Sure! Here you go:\n{"a": 2}\nHope that helps') == {"a": 2}
        assert ai._extract_json("not json at all") is None

    def test_placeholder_titles_are_rejected(self):
        """A small model echoing the schema must not become real nodes."""
        from src.services import mindmap_ai as ai

        assert ai._is_placeholder("Theme")
        assert ai._is_placeholder("Specific idea")
        assert ai._is_placeholder("<name of a theme>")
        assert not ai._is_placeholder("Offline sync for mobile")

    def test_coerce_drops_junk_and_clamps(self):
        from src.services import mindmap_ai as ai

        out = ai._coerce_tree([
            {"title": "Real theme", "node_type": "Feature",
             "children": [{"title": "Theme"}, {"title": "Real child"}]},
            {"title": ""},                       # empty -> dropped
            "not-a-dict",                        # wrong type -> dropped
            {"title": "Bad type", "node_type": "Nonsense"},
        ])
        assert [n["title"] for n in out] == ["Real theme", "Bad type"]
        # the echoed placeholder child is gone, the real one survives
        assert [c["title"] for c in out[0]["children"]] == ["Real child"]
        # an unknown node_type falls back to a valid one
        assert out[1]["node_type"] == "Idea"

    def test_generate_persists_the_returned_tree(self, db, monkeypatch):
        import asyncio

        from src.services import mindmap_ai as ai

        async def fake_json(prompt, what):
            return {
                "title": "Habit app",
                "children": [
                    {"title": "Onboarding", "node_type": "Feature",
                     "children": [{"title": "Streak setup", "node_type": "Idea"}]},
                ],
            }, None

        monkeypatch.setattr(ai, "_generate_json", fake_json)
        result = asyncio.run(ai.generate_map(db, PROJECT, "A habit app"))

        assert result["success"] is True
        assert result["nodes_created"] == 2
        tree = svc.get_map_tree(db, result["map_id"])
        assert tree["nodes"][0]["children"][0]["title"] == "Onboarding"

    def test_generate_surfaces_model_failure(self, db, monkeypatch):
        import asyncio

        from src.services import mindmap_ai as ai

        async def fake_json(prompt, what):
            return None, "bad json"

        monkeypatch.setattr(ai, "_generate_json", fake_json)
        result = asyncio.run(ai.generate_map(db, PROJECT, "x"))
        assert result["success"] is False and result["error"]

    def test_regroup_proposal_does_not_touch_the_map(self, db, a_map, monkeypatch):
        import asyncio

        from src.services import mindmap_ai as ai

        svc.create_node(db, a_map["id"], "Original", a_map["root_node_id"])
        before = len(svc.get_map_tree(db, a_map["id"])["flat"])

        async def fake_json(prompt, what):
            return {"title": "New", "children": [{"title": "Regrouped", "node_type": "Idea"}]}, None

        monkeypatch.setattr(ai, "_generate_json", fake_json)
        result = asyncio.run(ai.regroup_map(db, a_map["id"]))

        assert result["success"] is True
        assert result["proposed"]["children"][0]["title"] == "Regrouped"
        assert len(svc.get_map_tree(db, a_map["id"])["flat"]) == before, "preview must not persist"

    def test_apply_regroup_snapshots_then_replaces(self, db, a_map):
        from src.services import mindmap_ai as ai

        svc.create_node(db, a_map["id"], "Original", a_map["root_node_id"])
        proposed = {"title": "Reorganized",
                    "children": [{"title": "New theme", "node_type": "Idea",
                                  "description": "", "children": []}]}

        result = ai.apply_regroup(db, a_map["id"], proposed)
        assert result["success"] is True

        tree = svc.get_map_tree(db, a_map["id"])
        titles = [n["title"] for n in tree["flat"]]
        assert "New theme" in titles and "Original" not in titles

        snaps = svc.list_snapshots(db, a_map["id"])
        assert snaps and snaps[0]["label"] == "before AI regroup"

    def test_restore_snapshot_brings_deleted_nodes_back(self, db, a_map):
        """Snapshot restore is what lets undo recover a deletion."""
        child = svc.create_node(db, a_map["id"], "Keep me", a_map["root_node_id"])
        snapshot_id = svc.save_snapshot(db, a_map["id"],
                                        svc.get_map_tree(db, a_map["id"]), "before delete")

        svc.delete_node(db, child["id"])
        assert len(svc.get_map_tree(db, a_map["id"])["flat"]) == 1

        svc.restore_snapshot(db, a_map["id"], snapshot_id)
        titles = [n["title"] for n in svc.get_map_tree(db, a_map["id"])["flat"]]
        assert "Keep me" in titles, "restore must resurrect deleted nodes"


# ---------------------------------------------------------------------------
# Export / import (Phase 3)
# ---------------------------------------------------------------------------
class TestExportImport:
    def _sample(self, db, a_map):
        theme = svc.create_node(db, a_map["id"], "Onboarding", a_map["root_node_id"],
                                "Feature", description="First run")
        svc.create_node(db, a_map["id"], "Streak setup", theme["id"], "Idea")
        return theme

    def test_json_roundtrip_preserves_structure(self, db, a_map):
        from src.services import mindmap_export as ex

        self._sample(db, a_map)
        payload = ex.export_json(db, a_map["id"])
        assert payload["format"] == "dobby.mindmap"

        result = ex.import_json(db, PROJECT, payload)
        assert result["success"] is True

        original = svc.get_map_tree(db, a_map["id"])
        copy = svc.get_map_tree(db, result["map_id"])
        assert len(copy["flat"]) == len(original["flat"])
        assert sorted(n["title"] for n in copy["flat"]) == \
               sorted(n["title"] for n in original["flat"])
        # fresh ids — an import must never collide with the source
        assert not {n["id"] for n in copy["flat"]} & {n["id"] for n in original["flat"]}

    def test_markdown_outline_shape(self, db, a_map):
        from src.services import mindmap_export as ex

        self._sample(db, a_map)
        md = ex.export_markdown(db, a_map["id"])
        assert md.startswith("# Test map")
        assert "## Onboarding" in md          # top-level themes become H2
        assert "- **Streak setup**" in md      # deeper nodes become bullets

    def test_mermaid_is_valid_mindmap_syntax(self, db, a_map):
        from src.services import mindmap_export as ex

        self._sample(db, a_map)
        mm = ex.export_mermaid(db, a_map["id"])
        lines = mm.splitlines()
        assert lines[0] == "mindmap"
        assert lines[1].strip().startswith("root((")
        assert any("Onboarding" in l for l in lines)

    def test_mermaid_strips_breaking_characters(self, db, a_map):
        from src.services import mindmap_export as ex

        svc.create_node(db, a_map["id"], "Auth (OAuth) [beta]", a_map["root_node_id"])
        mm = ex.export_mermaid(db, a_map["id"])
        body = "\n".join(mm.splitlines()[2:])
        # brackets would break Mermaid node labels
        assert "(" not in body and "[" not in body
        assert "Auth OAuth beta" in body

    def test_import_rejects_missing_nodes(self, db):
        from src.services import mindmap_export as ex

        with pytest.raises(ex.ImportError_, match="nodes"):
            ex.import_json(db, PROJECT, {"map": {"title": "x"}})

    def test_import_rejects_missing_title(self, db):
        from src.services import mindmap_export as ex

        with pytest.raises(ex.ImportError_, match="title"):
            ex.import_json(db, PROJECT, {"nodes": [{"id": "a"}]})

    def test_import_rejects_dangling_parent(self, db):
        from src.services import mindmap_export as ex

        with pytest.raises(ex.ImportError_, match="missing parent"):
            ex.import_json(db, PROJECT, {
                "nodes": [{"id": "a", "title": "A", "parent_id": "ghost"}]
            })

    def test_import_rejects_a_cycle(self, db):
        from src.services import mindmap_export as ex

        with pytest.raises(ex.ImportError_, match="cycle"):
            ex.import_json(db, PROJECT, {
                "nodes": [
                    {"id": "a", "title": "A", "parent_id": "b"},
                    {"id": "b", "title": "B", "parent_id": "a"},
                ]
            })

    def test_export_endpoints_over_http(self, client, db, a_map):
        self._sample(db, a_map)
        mid = a_map["id"]

        assert client.get(f"/api/v1/mindmaps/map/{mid}/export/json").status_code == 200
        md = client.get(f"/api/v1/mindmaps/map/{mid}/export/markdown")
        assert md.status_code == 200 and md.text.startswith("# ")
        mm = client.get(f"/api/v1/mindmaps/map/{mid}/export/mermaid")
        assert mm.status_code == 200 and mm.text.startswith("mindmap")

    def test_bad_import_returns_400_with_reason(self, client):
        r = client.post(f"/api/v1/mindmaps/import/{PROJECT}",
                        json={"data": {"nodes": [{"id": "a"}]}})
        assert r.status_code == 400
        assert "title" in r.json()["detail"]
