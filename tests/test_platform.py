"""
Scale, ecosystem & ritual — i18n, model catalog, in-app help, goals,
recommendations, admin console, ritual mode.

The rules that matter: English must append nothing to prompts so the default
path is unchanged, help must stay usable when no model is available, and goal
steps must be derived from real data rather than stored.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_platform_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import idea_service, platform_service as svc  # noqa: E402

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


class TestLanguage:
    def test_english_appends_nothing(self, monkeypatch):
        monkeypatch.setattr(svc, "get_language", lambda: {"code": "en", "name": "English"})
        # The default path must be byte-identical to before this feature.
        assert svc.language_instruction() == ""

    def test_other_language_adds_an_instruction(self, monkeypatch):
        monkeypatch.setattr(svc, "get_language", lambda: {"code": "ja", "name": "Japanese"})
        out = svc.language_instruction()
        assert "Japanese" in out
        assert "identifiers" in out  # code must not be translated

    def test_unsupported_language_rejected(self):
        with pytest.raises(svc.PlatformError):
            svc.set_language("klingon")

    def test_catalog_covers_the_common_ones(self):
        assert {"en", "es", "fr", "de", "ja", "zh"} <= set(svc.LANGUAGES)


class TestModelCatalog:
    @pytest.mark.asyncio
    async def test_catalog_annotates_fit(self):
        out = await svc.model_catalog()
        assert out["models"]
        for m in out["models"]:
            assert "installed" in m and "pull_command" in m

    @pytest.mark.asyncio
    async def test_survives_ollama_being_down(self, monkeypatch):
        # A dead Ollama must not make the catalog unusable.
        class Boom:
            async def list_models(self):
                raise RuntimeError("connection refused")

        monkeypatch.setattr("src.llm.ollama_client.OllamaClient", lambda *a, **k: Boom())
        out = await svc.model_catalog()
        assert out["ollama_reachable"] is False
        assert out["models"]

    @pytest.mark.asyncio
    async def test_states_dobby_does_not_download(self):
        out = await svc.model_catalog()
        assert "never downloads" in out["note"]


class TestHelp:
    def test_finds_documented_topics(self):
        out = svc.search_help("how do I capture an idea")
        assert out["searched"] > 0
        assert out["hits"]

    def test_blank_question_returns_nothing(self):
        assert svc.search_help("   ")["hits"] == []

    def test_stopwords_alone_find_nothing(self):
        assert svc.search_help("the a of and")["hits"] == []

    def test_hits_cite_a_source_and_heading(self):
        out = svc.search_help("streak")
        if out["hits"]:
            assert out["hits"][0]["source"].endswith(".md")
            assert "heading" in out["hits"][0]

    @pytest.mark.asyncio
    async def test_stays_usable_without_a_model(self, db, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("no model")

        monkeypatch.setattr("src.services.model_routing.call", boom)
        out = await svc.answer_help(db, "how do I capture an idea")
        # The retrieved sections are already the answer, just unsummarised.
        assert out["model_unavailable"] is True
        assert out["sources"]

    @pytest.mark.asyncio
    async def test_unknown_topic_says_so(self, db):
        out = await svc.answer_help(db, "zzzqqq nonexistent topic xyzzy")
        assert out["grounded"] is False


class TestGoals:
    def test_steps_are_derived_from_real_state(self, db):
        idea_service.capture(db, PROJECT, "goal progress trigger")
        goals = svc.goal_progress(db, PROJECT)
        mvp = next(g for g in goals if g["slug"] == "mvp_spec_set")
        capture_step = next(s for s in mvp["steps"] if s["key"] == "capture")
        assert capture_step["done"] is True

    def test_next_step_is_the_first_unfinished(self, db):
        goals = svc.goal_progress(db, PROJECT)
        for g in goals:
            if g["next_step"]:
                assert g["next_step"]["done"] is False

    def test_percent_matches_completed_count(self, db):
        for g in svc.goal_progress(db, PROJECT):
            expected = round(100.0 * g["completed"] / g["total"], 1)
            assert g["percent"] == expected

    def test_every_goal_is_returned(self, db):
        assert len(svc.goal_progress(db, PROJECT)) == len(svc.GUIDED_GOALS)


class TestRecommendations:
    @pytest.mark.asyncio
    async def test_returns_actionable_items(self, db):
        out = await svc.recommendations(db, PROJECT)
        for r in out["recommendations"]:
            assert r["title"] and r["route"]

    @pytest.mark.asyncio
    async def test_flags_untriaged_pile(self, db):
        for i in range(6):
            idea_service.capture(db, PROJECT, f"pile item number {i}")
        out = await svc.recommendations(db, PROJECT)
        assert any(r["kind"] == "template" for r in out["recommendations"])


class TestAdminConsole:
    def test_aggregates_across_projects(self, db):
        out = svc.admin_console(db)
        assert out["project_count"] >= 1
        assert "documents" in out["totals"]

    def test_states_it_is_machine_local(self, db):
        assert "machine only" in svc.admin_console(db)["scope"]


class TestRitual:
    @pytest.mark.asyncio
    async def test_assembles_the_whole_flow(self, db, monkeypatch):
        async def fake_call(*a, **k):
            return "do the thing"

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        out = await svc.start_your_day(db, PROJECT)
        assert out["greeting"]
        assert {"review", "focus", "plan"} <= {s["key"] for s in out["steps"]}
        assert "streak" in out


class TestRoutes:
    def test_meta_lists_languages_and_goals(self, client):
        body = client.get("/api/v1/platform/meta").json()
        assert "en" in body["languages"] and body["goals"]

    def test_bad_language_400s(self, client):
        assert client.post("/api/v1/platform/language",
                           json={"code": "xx"}).status_code == 400

    def test_help_endpoint(self, client):
        r = client.get("/api/v1/platform/help", params={"q": "capture an idea"})
        assert r.status_code == 200 and "hits" in r.json()

    def test_models_endpoint(self, client):
        assert client.get("/api/v1/platform/models").status_code == 200

    def test_goals_endpoint(self, client):
        assert client.get(f"/api/v1/platform/goals/{PROJECT}").status_code == 200

    def test_admin_endpoint(self, client):
        assert client.get("/api/v1/platform/admin").status_code == 200
