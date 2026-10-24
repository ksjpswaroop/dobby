"""
AI chat editing.

The model is stubbed here on purpose. What matters is not whether a particular
local model writes good markdown, but that a *bad* response cannot quietly
destroy someone's map — so the guards are tested against the exact failure modes
small models exhibit: truncated output, prose preamble, and fenced code blocks.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_chat_test_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import mindmap_ai, mindmap_outline as ol, mindmap_service as svc  # noqa: E402

PROJECT = "default-project"

FULL = """# Plan
## Alpha
### A1
### A2
## Beta
### B1
## Gamma
### G1
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


@pytest.fixture
def a_map(db):
    return ol.import_outline(db, PROJECT, FULL)["map_id"]


@pytest.fixture
def stub_model(monkeypatch):
    """Make the model return whatever the test wants."""

    def _install(reply: str):
        class FakeClient:
            async def generate(self, *a, **k):
                return reply

            async def close(self):
                pass

        async def fake_get(*a, **k):
            return FakeClient()

        monkeypatch.setattr(mindmap_ai, "get_ollama_client", fake_get)

    return _install


async def _edit(db, map_id, instruction="reorganise this"):
    return await mindmap_ai.chat_edit(db, map_id, instruction)


class TestGuards:
    @pytest.mark.asyncio
    async def test_a_truncated_reply_is_rejected(self, db, a_map, stub_model):
        """The commonest failure: the model returns only the part it edited."""
        stub_model("# Plan\n## Alpha\n")
        result = await _edit(db, a_map, "add more detail to Alpha")

        assert result["success"] is False
        assert "would have deleted most of your map" in result["error"]
        # Crucially, the map is untouched.
        tree = svc.get_map_tree(db, a_map)
        assert {n["title"] for n in tree["flat"]} >= {"Alpha", "Beta", "Gamma"}

    @pytest.mark.asyncio
    async def test_deletion_is_allowed_when_it_was_asked_for(self, db, a_map, stub_model):
        """The same small reply must go through if the user asked to trim."""
        stub_model("# Plan\n## Alpha\n")
        result = await _edit(db, a_map, "delete everything except Alpha")

        assert result["success"] is True
        titles = {n["title"] for n in svc.get_map_tree(db, a_map)["flat"]}
        assert "Beta" not in titles and "Gamma" not in titles

    @pytest.mark.asyncio
    async def test_unparseable_output_leaves_the_map_alone(self, db, a_map, stub_model):
        stub_model("Sure! I'd be happy to help you with that.")
        result = await _edit(db, a_map)

        assert result["success"] is False
        assert "outline" in result["error"].lower()
        assert len(svc.get_map_tree(db, a_map)["flat"]) == 8

    @pytest.mark.asyncio
    async def test_code_fences_are_stripped(self, db, a_map, stub_model):
        stub_model("```markdown\n# Plan\n## Alpha\n## Beta\n## Gamma\n## Delta\n```")
        result = await _edit(db, a_map, "add Delta")

        assert result["success"] is True
        assert "Delta" in {n["title"] for n in svc.get_map_tree(db, a_map)["flat"]}

    @pytest.mark.asyncio
    async def test_an_empty_instruction_is_refused_without_calling_the_model(self, db, a_map):
        result = await mindmap_ai.chat_edit(db, a_map, "   ")
        assert result["success"] is False
        assert "what you'd like changed" in result["error"]

    @pytest.mark.asyncio
    async def test_a_successful_edit_leaves_a_restore_point(self, db, a_map, stub_model):
        stub_model("# Plan\n## Alpha\n## Beta\n## Gamma\n## Delta\n")
        await _edit(db, a_map, "add Delta")

        snapshots = svc.list_snapshots(db, a_map)
        assert snapshots, "a chat edit must be undoable"
        svc.restore_snapshot(db, a_map, snapshots[0]["id"])
        assert "Delta" not in {n["title"] for n in svc.get_map_tree(db, a_map)["flat"]}

    @pytest.mark.asyncio
    async def test_small_maps_are_not_guarded(self, db, stub_model):
        """The guard needs a baseline; a 2-node map can legitimately halve."""
        map_id = ol.import_outline(db, PROJECT, "# Tiny\n## One\n## Two\n")["map_id"]
        stub_model("# Tiny\n## One\n")
        result = await _edit(db, map_id, "make it simpler still")
        assert result["success"] is True


class TestApi:
    def test_chat_endpoint_reports_counts(self, client, db, a_map, stub_model):
        # A faithful reply: the whole map back, plus the requested branch.
        stub_model(FULL + "## Delta\n### D1\n")
        r = client.post(f"/api/v1/mindmaps/ai/chat/{a_map}",
                        json={"instruction": "add a Delta branch"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["nodes_before"] == 7
        assert body["nodes_after"] == 9

    def test_a_rejected_edit_is_422_with_a_reason(self, client, a_map, stub_model):
        stub_model("# Plan\n## Alpha\n")
        r = client.post(f"/api/v1/mindmaps/ai/chat/{a_map}",
                        json={"instruction": "expand everything"})
        assert r.status_code == 422
        assert "deleted most of your map" in r.json()["detail"]

    def test_an_empty_instruction_is_rejected_by_validation(self, client, a_map):
        r = client.post(f"/api/v1/mindmaps/ai/chat/{a_map}", json={"instruction": ""})
        assert r.status_code == 422
