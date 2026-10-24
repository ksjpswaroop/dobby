"""
Skills — intent, sources, guardrails, approval.

The rules that matter: a guardrail must be enforced in code rather than
requested in the prompt, a simulation must write nothing, acting must pass
the approval gate, and a skill nobody has watched run must not be publishable.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_skills_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import Node, Project  # noqa: E402
from src.main import app  # noqa: E402
from src.services import skill_service as svc  # noqa: E402

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
def proj(db):
    """A project of this test's own — the suite shares one database."""
    pid = f"sk-{uuid.uuid4().hex[:8]}"
    with db.get_session() as s:
        s.add(Project(id=pid, name="Skill test"))
        s.commit()
    return pid


@pytest.fixture
def stub_model(monkeypatch):
    async def fake_call(*a, **k):
        return "A perfectly reasonable generated answer about the thing."

    monkeypatch.setattr("src.services.model_routing.call", fake_call)


@pytest.fixture
def auto_approve(monkeypatch):
    async def approve(*a, **k):
        return "approved"

    monkeypatch.setattr("src.services.inbox_service.require", approve)


@pytest.fixture
def auto_deny(monkeypatch):
    async def deny(*a, **k):
        return "denied"

    monkeypatch.setattr("src.services.inbox_service.require", deny)


def a_skill(db, proj, **over):
    kwargs = dict(name=over.pop("name", f"Skill {uuid.uuid4().hex[:6]}"),
                  prompt="Answer this: {{input}}\n\nContext:\n{{context}}",
                  sources=["project_documents"], rules=["Be concise."])
    kwargs.update(over)
    return svc.create(db, proj, **kwargs)


class TestValidation:
    def test_unknown_source_rejected(self, db, proj):
        with pytest.raises(svc.SkillError):
            a_skill(db, proj, sources=["read_my_email"])

    def test_unknown_approval_mode_rejected(self, db, proj):
        with pytest.raises(svc.SkillError):
            a_skill(db, proj, approval_mode="whatever")

    def test_unknown_output_action_rejected(self, db, proj):
        with pytest.raises(svc.SkillError):
            a_skill(db, proj, output_action="rm_rf")

    def test_local_only_refuses_a_network_source(self, db, proj):
        # A contradiction the user should be told about, not silently resolved.
        with pytest.raises(svc.SkillError) as e:
            a_skill(db, proj, sources=["web_search"], local_only=True)
        assert "local-only" in str(e.value)

    def test_web_source_allowed_when_local_only_is_off(self, db, proj):
        sk = a_skill(db, proj, sources=["web_search"], local_only=False)
        assert "web_search" in sk["sources"]

    def test_blank_prompt_rejected(self, db, proj):
        with pytest.raises(svc.SkillError):
            svc.create(db, proj, "No intent", prompt="   ")

    def test_duplicate_slug_rejected(self, db, proj):
        a_skill(db, proj, name="Unique Skill")
        with pytest.raises(svc.SkillError):
            a_skill(db, proj, name="Unique Skill")


class TestPermissions:
    def test_permissions_state_can_and_cannot(self, db, proj):
        sk = a_skill(db, proj, sources=["project_documents"])
        perms = sk["permissions"]
        assert "Read your project documents" in perms["can"]
        assert "Search the web" in perms["cannot"]
        assert "Run code or install anything" in perms["cannot"]

    def test_local_only_promises_data_stays(self, db, proj):
        sk = a_skill(db, proj, local_only=True)
        assert "Send your data anywhere" in sk["permissions"]["cannot"]

    def test_return_only_cannot_change_anything(self, db, proj):
        sk = a_skill(db, proj, output_action="return_only")
        assert "Make any changes" in sk["permissions"]["cannot"]

    def test_writing_skill_says_it_needs_approval(self, db, proj):
        sk = a_skill(db, proj, output_action="capture_idea", approval_mode="manual")
        assert any("with your approval" in c for c in sk["permissions"]["can"])


class TestGuardrails:
    @pytest.mark.asyncio
    async def test_word_limit_is_enforced_in_code(self, db, proj, monkeypatch):
        async def long_answer(*a, **k):
            return " ".join(["word"] * 200)

        monkeypatch.setattr("src.services.model_routing.call", long_answer)
        sk = a_skill(db, proj, max_output_words=10)
        out = await svc.run(db, sk["id"], "anything")
        assert out["ok"] is False
        assert "limit is 10" in out["error"]

    @pytest.mark.asyncio
    async def test_placeholders_are_rejected(self, db, proj, monkeypatch):
        async def lazy(*a, **k):
            return "Here is the answer.\n\nTODO: finish this section"

        monkeypatch.setattr("src.services.model_routing.call", lazy)
        sk = a_skill(db, proj)
        out = await svc.run(db, sk["id"], "x")
        assert out["ok"] is False
        assert "TODO" in out["error"]

    @pytest.mark.asyncio
    async def test_a_clean_output_passes(self, db, proj, stub_model):
        sk = a_skill(db, proj)
        out = await svc.run(db, sk["id"], "x")
        assert out["ok"] is True
        assert any(t["step"] == "guardrails" and t["ok"] for t in out["trace"])


class TestSimulation:
    @pytest.mark.asyncio
    async def test_simulation_writes_nothing(self, db, proj, stub_model):
        sk = a_skill(db, proj, output_action="capture_idea")
        from src.services import idea_service

        before = len(idea_service.list_ideas(db, proj))
        out = await svc.run(db, sk["id"], "an input", simulate=True)
        assert out["simulated"] is True
        assert out["ok"] is True
        assert len(idea_service.list_ideas(db, proj)) == before

    @pytest.mark.asyncio
    async def test_simulation_says_what_it_would_have_done(self, db, proj, stub_model):
        sk = a_skill(db, proj, output_action="save_document")
        out = await svc.run(db, sk["id"], "x", simulate=True)
        review = next(t for t in out["trace"] if t["step"] == "review")
        assert "would have run" in review["detail"]

    @pytest.mark.asyncio
    async def test_simulation_is_still_recorded(self, db, proj, stub_model):
        sk = a_skill(db, proj)
        await svc.run(db, sk["id"], "x", simulate=True)
        runs = svc.list_runs(db, sk["id"])
        # "What would this have done" is exactly the thing worth keeping.
        assert runs and runs[0]["simulated"] is True

    @pytest.mark.asyncio
    async def test_simulation_does_not_bump_the_run_count(self, db, proj, stub_model):
        sk = a_skill(db, proj)
        await svc.run(db, sk["id"], "x", simulate=True)
        assert svc.get(db, sk["id"])["run_count"] == 0


class TestApproval:
    @pytest.mark.asyncio
    async def test_acting_requires_approval(self, db, proj, stub_model, auto_deny):
        sk = a_skill(db, proj, output_action="capture_idea", approval_mode="manual")
        out = await svc.run(db, sk["id"], "x")
        assert out["ok"] is False
        assert out["produced"] is None

    @pytest.mark.asyncio
    async def test_approved_action_actually_happens(self, db, proj, stub_model, auto_approve):
        sk = a_skill(db, proj, output_action="capture_idea", approval_mode="manual")
        out = await svc.run(db, sk["id"], "x")
        assert out["ok"] is True
        assert out["produced"]["type"] == "idea"

    @pytest.mark.asyncio
    async def test_return_only_never_asks(self, db, proj, stub_model, auto_deny):
        # Nothing is being written, so an approval prompt would be pure friction.
        sk = a_skill(db, proj, output_action="return_only")
        out = await svc.run(db, sk["id"], "x")
        assert out["ok"] is True

    @pytest.mark.asyncio
    async def test_save_document_creates_a_real_node(self, db, proj, stub_model, auto_approve):
        sk = a_skill(db, proj, output_action="save_document",
                     output_params={"title": "From a skill"})
        out = await svc.run(db, sk["id"], "x")
        with db.get_session() as s:
            assert s.get(Node, out["produced"]["id"]).title == "From a skill"

    @pytest.mark.asyncio
    async def test_create_decision_action(self, db, proj, monkeypatch, auto_approve):
        async def framed(*a, **k):
            return "RAG vs. structured reasoning\n- Use RAG\n- Use structured reasoning"

        monkeypatch.setattr("src.services.model_routing.call", framed)
        sk = a_skill(db, proj, output_action="create_decision")
        out = await svc.run(db, sk["id"], "which approach?")

        from src.services import decision_service

        d = decision_service.get(db, out["produced"]["id"])
        assert d["title"].startswith("RAG vs")
        assert len(d["options"]) == 2


class TestPublishing:
    def test_cannot_publish_without_a_simulation(self, db, proj):
        sk = a_skill(db, proj)
        with pytest.raises(svc.SkillError) as e:
            svc.publish(db, sk["id"])
        assert "simulation" in str(e.value)

    @pytest.mark.asyncio
    async def test_publish_after_a_successful_simulation(self, db, proj, stub_model):
        sk = a_skill(db, proj)
        await svc.run(db, sk["id"], "x", simulate=True)
        assert svc.publish(db, sk["id"])["state"] == "published"

    def test_new_skills_start_as_drafts(self, db, proj):
        assert a_skill(db, proj)["state"] == "draft"


class TestBuiltins:
    def test_seeding_is_idempotent(self, db):
        svc.seed_builtins(db)
        assert svc.seed_builtins(db) == 0

    def test_the_generator_ships_as_a_skill(self, db, proj):
        svc.seed_builtins(db)
        skills = svc.list_skills(db, proj)
        seven = next((s for s in skills if s["slug"] == "seven_artifact_set"), None)
        # The core generator is one skill among many — a promotion of the
        # frame, not a demotion of the feature.
        assert seven is not None and seven["builtin"] is True

    def test_builtins_cannot_be_edited(self, db, proj):
        svc.seed_builtins(db)
        builtin = next(s for s in svc.list_skills(db, proj) if s["builtin"])
        with pytest.raises(svc.SkillError):
            svc.update(db, builtin["id"], name="hijacked")

    def test_builtins_cannot_be_deleted(self, db, proj):
        svc.seed_builtins(db)
        builtin = next(s for s in svc.list_skills(db, proj) if s["builtin"])
        with pytest.raises(svc.SkillError):
            svc.delete(db, builtin["id"])

    def test_fork_a_builtin_into_a_project(self, db, proj):
        svc.seed_builtins(db)
        builtin = next(s for s in svc.list_skills(db, proj) if s["builtin"])
        fork = svc.fork(db, builtin["id"], proj)
        assert fork["builtin"] is False and fork["state"] == "draft"
        svc.update(db, fork["id"], name="My own version")

    @pytest.mark.asyncio
    async def test_a_builtin_must_be_forked_before_running(self, db):
        svc.seed_builtins(db)
        with db.get_session() as s:
            from src.db.skill_models import Skill

            builtin = s.query(Skill).filter(Skill.builtin == 1).first()
            bid = builtin.id
        with pytest.raises(svc.SkillError) as e:
            await svc.run(db, bid, "x")
        assert "fork" in str(e.value).lower()


class TestTrace:
    @pytest.mark.asyncio
    async def test_trace_covers_all_four_steps(self, db, proj, stub_model, auto_approve):
        sk = a_skill(db, proj, output_action="capture_idea")
        out = await svc.run(db, sk["id"], "x")
        steps = [t["step"] for t in out["trace"]]
        assert steps == ["sources", "intent", "guardrails", "review"]

    @pytest.mark.asyncio
    async def test_a_model_failure_is_recorded_not_raised(self, db, proj, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("model unavailable")

        monkeypatch.setattr("src.services.model_routing.call", boom)
        sk = a_skill(db, proj)
        out = await svc.run(db, sk["id"], "x")
        assert out["ok"] is False
        assert "unavailable" in out["error"]

    @pytest.mark.asyncio
    async def test_sources_step_reports_what_it_read(self, db, proj, stub_model):
        with db.get_session() as s:
            s.add(Node(id=str(uuid.uuid4()), project_id=proj,
                       node_type="documentation", title="Context doc",
                       content="Something useful."))
            s.commit()
        sk = a_skill(db, proj, sources=["project_documents"])
        out = await svc.run(db, sk["id"], "x")
        sources = next(t for t in out["trace"] if t["step"] == "sources")
        assert "project_documents" in sources["detail"]


class TestRoutes:
    def test_meta_lists_the_vocabulary(self, client):
        body = client.get("/api/v1/skills/meta").json()
        assert "project_documents" in body["sources"]
        assert "manual" in body["approval_modes"]

    def test_create_and_get(self, client, proj):
        r = client.post("/api/v1/skills", json={
            "project_id": proj, "name": "API skill", "prompt": "Do {{input}}"})
        assert r.status_code == 200
        assert client.get(f"/api/v1/skills/{r.json()['id']}").status_code == 200

    def test_contradictory_config_400s(self, client, proj):
        r = client.post("/api/v1/skills", json={
            "project_id": proj, "name": "Contradiction", "prompt": "x",
            "sources": ["web_search"], "local_only": True})
        assert r.status_code == 400

    def test_publish_without_simulation_409s(self, client, proj):
        created = client.post("/api/v1/skills", json={
            "project_id": proj, "name": "Unsimulated", "prompt": "x"}).json()
        assert client.post(f"/api/v1/skills/{created['id']}/publish").status_code == 409

    def test_unknown_skill_404s(self, client):
        assert client.get("/api/v1/skills/nope").status_code == 404
