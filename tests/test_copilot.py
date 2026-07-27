"""
AI Copilot — retrieval, next-best-action, prioritization, prompts, routing,
telemetry.

Model calls are stubbed throughout. What is worth testing here is not that
Ollama answers, but that retrieval ranks the right documents, that the
deterministic signal ordering is stable, that a score suggestion never
touches the backlog until accepted, and that telemetry survives a failure.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_copilot_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.schema import FeatureBacklog, Node  # noqa: E402
from src.main import app  # noqa: E402
from src.services import (  # noqa: E402
    copilot_service, model_telemetry, nba_service, prioritize_ai, prompt_library,
)

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


def make_node(db, title, content):
    node_id = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(Node(id=node_id, project_id=PROJECT, node_type="documentation",
                   title=title, content=content, status="draft"))
        s.commit()
    return node_id


def make_feature(db, title, impact=5, effort=5, risk=5, status="backlog"):
    fid = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(FeatureBacklog(
            id=fid, project_id=PROJECT, title=title, description=f"About {title}",
            category="core", impact_score=impact, effort_score=effort, risk_score=risk,
            pareto_score=(impact * 0.6) - (effort * 0.3) - (risk * 0.1), status=status))
        s.commit()
    return fid


class TestRetrieval:
    def test_title_match_outranks_body_mention(self, db):
        strong = make_node(db, "Authentication Design", "How login works here.")
        make_node(db, "Unrelated Notes", "we briefly mention authentication once")
        hits = copilot_service.retrieve(db, "authentication", PROJECT)
        assert hits[0]["node_id"] == strong

    def test_returns_nothing_for_unmatched_question(self, db):
        assert copilot_service.retrieve(db, "zzzqqqxxx nonexistent", PROJECT) == []

    def test_snippet_windows_around_the_match(self, db):
        filler = "padding. " * 80
        node_id = make_node(db, "Long Doc", filler + "THE MARKER IS HERE " + filler)
        hits = copilot_service.retrieve(db, "marker", PROJECT)
        hit = next(h for h in hits if h["node_id"] == node_id)
        assert "MARKER" in hit["snippet"]

    def test_stopwords_do_not_drive_ranking(self, db):
        assert copilot_service._terms("what is the a an of") == []


class TestThreads:
    def test_create_and_list(self, db):
        t = copilot_service.create_thread(db, PROJECT, "My chat")
        assert t["scope"] == "project"
        assert any(x["id"] == t["id"] for x in copilot_service.list_threads(db, PROJECT))

    def test_global_thread_has_global_scope(self, db):
        t = copilot_service.create_thread(db, None, "Global")
        assert t["scope"] == "global"
        assert any(x["id"] == t["id"]
                   for x in copilot_service.list_threads(db, None, scope="global"))

    def test_delete_removes_messages_too(self, db):
        t = copilot_service.create_thread(db, PROJECT)
        assert copilot_service.delete_thread(db, t["id"]) is True
        assert copilot_service.list_messages(db, t["id"]) == []

    @pytest.mark.asyncio
    async def test_ask_stores_answer_with_citations(self, db, monkeypatch):
        make_node(db, "Payment Flow", "Payments are processed by the billing service.")
        t = copilot_service.create_thread(db, PROJECT)

        async def fake_call(*a, **k):
            return "Payments go through the billing service [1]."

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        msg = await copilot_service.ask(db, t["id"], "how are payments processed?")
        assert msg["role"] == "assistant"
        assert msg["citations"]
        assert copilot_service.list_messages(db, t["id"])[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_first_question_titles_the_thread(self, db, monkeypatch):
        t = copilot_service.create_thread(db, PROJECT)

        async def fake_call(*a, **k):
            return "answer"

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        await copilot_service.ask(db, t["id"], "what is the deployment story?")
        titles = {x["id"]: x["title"] for x in copilot_service.list_threads(db, PROJECT)}
        assert titles[t["id"]].startswith("what is the deployment story")

    @pytest.mark.asyncio
    async def test_blank_question_rejected(self, db):
        t = copilot_service.create_thread(db, PROJECT)
        with pytest.raises(copilot_service.CopilotError):
            await copilot_service.ask(db, t["id"], "   ")


class TestNextBestAction:
    def test_signals_are_ordered_by_urgency(self, db):
        sug = nba_service.compute(db, PROJECT)
        weights = [s["weight"] for s in sug]
        assert weights == sorted(weights, reverse=True)

    def test_high_pareto_feature_is_suggested(self, db):
        make_feature(db, "Very valuable thing", impact=10, effort=1, risk=1)
        kinds = {s["kind"] for s in nba_service.compute(db, PROJECT)}
        assert "high_pareto_unstarted" in kinds

    @pytest.mark.asyncio
    async def test_falls_back_to_deterministic_wording_when_model_fails(self, db, monkeypatch):
        make_feature(db, "Fallback check", impact=9, effort=1, risk=1)

        async def boom(*a, **k):
            raise RuntimeError("model down")

        monkeypatch.setattr("src.services.model_routing.call", boom)
        out = await nba_service.next_best_action(db, PROJECT)
        assert out["phrased_by_model"] is False
        assert out["message"]

    @pytest.mark.asyncio
    async def test_model_phrasing_is_used_when_available(self, db, monkeypatch):
        make_feature(db, "Phrasing check", impact=9, effort=1, risk=1)

        async def fake_call(*a, **k):
            return "Start the highest-value thing."

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        out = await nba_service.next_best_action(db, PROJECT)
        assert out["phrased_by_model"] is True


class TestPrioritization:
    @pytest.mark.asyncio
    async def test_suggestion_does_not_touch_the_feature(self, db, monkeypatch):
        fid = make_feature(db, "Untouched feature", impact=5, effort=5, risk=5)

        async def fake_call(*a, **k):
            return '{"impact": 9, "effort": 2, "risk": 1, "confidence": 0.8, "rationale": "high value"}'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        sug = await prioritize_ai.suggest_scores(db, PROJECT, fid)
        assert sug["suggested"]["impact"] == 9
        with db.get_session() as s:
            assert s.get(FeatureBacklog, fid).impact_score == 5  # unchanged

    @pytest.mark.asyncio
    async def test_accept_applies_and_recomputes_pareto(self, db, monkeypatch):
        fid = make_feature(db, "Accept me", impact=5, effort=5, risk=5)

        async def fake_call(*a, **k):
            return '{"impact": 10, "effort": 2, "risk": 2, "confidence": 0.9, "rationale": "x"}'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        sug = await prioritize_ai.suggest_scores(db, PROJECT, fid)
        out = prioritize_ai.accept(db, sug["id"])
        assert out["impact"] == 10
        assert out["pareto"] == pytest.approx((10 * 0.6) - (2 * 0.3) - (2 * 0.1))

    @pytest.mark.asyncio
    async def test_accept_honours_user_edits(self, db, monkeypatch):
        fid = make_feature(db, "Edit me")

        async def fake_call(*a, **k):
            return '{"impact": 9, "effort": 3, "risk": 3, "confidence": 0.7, "rationale": "x"}'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        sug = await prioritize_ai.suggest_scores(db, PROJECT, fid)
        out = prioritize_ai.accept(db, sug["id"], impact=6)
        assert out["impact"] == 6

    @pytest.mark.asyncio
    async def test_out_of_range_scores_are_clamped(self, db, monkeypatch):
        fid = make_feature(db, "Clamp me")

        async def fake_call(*a, **k):
            return '{"impact": 99, "effort": -5, "risk": 3, "confidence": 2, "rationale": "x"}'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        sug = await prioritize_ai.suggest_scores(db, PROJECT, fid)
        assert sug["suggested"]["impact"] == 10
        assert sug["suggested"]["effort"] == 1
        assert sug["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_unparseable_model_output_raises(self, db, monkeypatch):
        fid = make_feature(db, "Bad json")

        async def fake_call(*a, **k):
            return "I think it is pretty important honestly"

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        with pytest.raises(prioritize_ai.PrioritizeError):
            await prioritize_ai.suggest_scores(db, PROJECT, fid)

    @pytest.mark.asyncio
    async def test_reject_leaves_feature_alone(self, db, monkeypatch):
        fid = make_feature(db, "Reject me", impact=4)

        async def fake_call(*a, **k):
            return '{"impact": 10, "effort": 1, "risk": 1, "confidence": 1, "rationale": "x"}'

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        sug = await prioritize_ai.suggest_scores(db, PROJECT, fid)
        assert prioritize_ai.reject(db, sug["id"]) is True
        with db.get_session() as s:
            assert s.get(FeatureBacklog, fid).impact_score == 4

    def test_json_extraction_handles_fences(self):
        out = prioritize_ai._extract_json('```json\n{"impact": 7}\n```')
        assert out == {"impact": 7}


class TestPromptLibrary:
    def test_builtins_seed_idempotently(self, db):
        prompt_library.seed_builtins(db)
        again = prompt_library.seed_builtins(db)
        assert again == 0

    def test_variables_are_declared(self):
        assert prompt_library.declared_variables("Hi {{name}}, see {{doc}} and {{name}}") \
            == ["name", "doc"]

    def test_builtin_cannot_be_edited(self, db):
        prompt_library.seed_builtins(db)
        builtin = next(p for p in prompt_library.list_prompts(db, PROJECT) if p["builtin"])
        with pytest.raises(prompt_library.PromptError):
            prompt_library.update_prompt(db, builtin["id"], body="hacked")

    def test_fork_then_edit(self, db):
        prompt_library.seed_builtins(db)
        builtin = next(p for p in prompt_library.list_prompts(db, PROJECT) if p["builtin"])
        fork = prompt_library.fork_prompt(db, builtin["id"], PROJECT)
        assert fork["forked_from"] == builtin["id"]
        updated = prompt_library.update_prompt(db, fork["id"], body="my {{version}}")
        assert updated["variables"] == ["version"]

    def test_diff_against_origin(self, db):
        prompt_library.seed_builtins(db)
        builtin = next(p for p in prompt_library.list_prompts(db, PROJECT) if p["builtin"])
        fork = prompt_library.fork_prompt(db, builtin["id"], PROJECT)
        prompt_library.update_prompt(db, fork["id"], body="totally different")
        out = prompt_library.diff_against_origin(db, fork["id"])
        assert any(l.startswith("+totally different") for l in out["diff"])

    def test_render_requires_every_variable(self, db):
        p = prompt_library.create_prompt(db, PROJECT, "Needs vars", "Hello {{a}} and {{b}}")
        with pytest.raises(prompt_library.PromptError):
            prompt_library.render(db, p["id"], {"a": "x"})
        out = prompt_library.render(db, p["id"], {"a": "x", "b": "y"})
        assert out["rendered"] == "Hello x and y"

    def test_duplicate_name_rejected(self, db):
        prompt_library.create_prompt(db, PROJECT, "Unique Prompt", "body")
        with pytest.raises(prompt_library.PromptError):
            prompt_library.create_prompt(db, PROJECT, "Unique Prompt", "body")


class TestTelemetry:
    def test_records_a_call(self, db):
        model_telemetry.record(db, "chat", "llama3.2", project_id=PROJECT,
                               prompt="hello", output="world", latency_ms=120)
        out = model_telemetry.usage(db, PROJECT, days=1)
        assert out["total_calls"] >= 1

    def test_failures_are_logged_not_swallowed(self, db):
        model_telemetry.record(db, "chat", "llama3.2", project_id=PROJECT,
                               prompt="x", ok=False, error="timeout", latency_ms=5)
        out = model_telemetry.usage(db, PROJECT, days=1)
        assert out["failures"] >= 1

    def test_unknown_task_type_becomes_other(self, db):
        model_telemetry.record(db, "not-a-task", "m", project_id=PROJECT)
        tasks = {t["task_type"] for t in model_telemetry.usage(db, PROJECT, days=1)["by_task"]}
        assert "other" in tasks

    def test_cost_is_labelled_as_an_estimate(self, db):
        out = model_telemetry.usage(db, PROJECT, days=1)
        assert out["tokens_are_estimated"] is True
        assert "estimate" in out["cost_basis"]["note"].lower()

    def test_recent_lists_calls(self, db):
        model_telemetry.record(db, "summarize", "m2", project_id=PROJECT, latency_ms=9)
        assert model_telemetry.recent(db, 10, PROJECT)


class TestRouting:
    def test_explicit_model_beats_route(self):
        from src.services import model_routing
        assert model_routing.resolve("chat", "explicit-model") == "explicit-model"

    def test_unknown_task_type_rejected(self):
        from src.services import model_routing
        with pytest.raises(ValueError):
            model_routing.set_route("not-a-task", "m")

    def test_routing_table_lists_unrouted(self):
        from src.services import model_routing
        table = model_routing.routing_table()
        assert "chat" in table["task_types"]


class TestRoutes:
    def test_signals_endpoint(self, client):
        r = client.get(f"/api/v1/copilot/signals/{PROJECT}")
        assert r.status_code == 200 and "suggestions" in r.json()

    def test_prompts_endpoint_lists_builtins(self, client):
        r = client.get("/api/v1/copilot/prompts", params={"project_id": PROJECT})
        assert r.status_code == 200
        assert any(p["builtin"] for p in r.json()["prompts"])

    def test_usage_endpoint(self, client):
        r = client.get("/api/v1/copilot/usage", params={"project_id": PROJECT})
        assert r.status_code == 200 and "by_model" in r.json()

    def test_routing_endpoint(self, client):
        assert client.get("/api/v1/copilot/routing").status_code == 200

    def test_thread_create_and_ask_unknown_404s(self, client):
        r = client.post("/api/v1/copilot/threads/nope/ask", json={"question": "hi"})
        assert r.status_code == 404

    def test_retrieve_endpoint(self, client):
        r = client.get("/api/v1/copilot/retrieve",
                       params={"question": "authentication", "project_id": PROJECT})
        assert r.status_code == 200 and "hits" in r.json()
