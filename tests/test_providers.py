"""
Model provider abstraction.

Network calls are stubbed at the httpx layer, so what is tested is the thing
that actually varies between providers: request shape, response parsing, and
the routing rules. The rule that matters most is that routing prefers a local
model — a layer that quietly reaches for a hosted model would undo the app's
premise without anyone noticing.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_prov_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.llm import providers as P  # noqa: E402
from src.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture
def capture(monkeypatch):
    """Record outgoing requests and return a canned reply."""
    sent = {}

    def _install(payload, status=200):
        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def get(self, url, **kw):
                sent.update({"method": "GET", "url": url, **kw})
                return FakeResponse(payload, status)

            async def post(self, url, **kw):
                sent.update({"method": "POST", "url": url, **kw})
                return FakeResponse(payload, status)

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())
        return sent

    return _install


class TestCapabilityInference:
    def test_a_local_model_is_marked_local(self):
        caps, _ = P._infer_capabilities("llama3.2", "ollama", True)
        assert P.Capability.LOCAL in caps

    def test_a_hosted_model_is_not(self):
        caps, _ = P._infer_capabilities("gpt-4o", "openai", False)
        assert P.Capability.LOCAL not in caps

    def test_large_context_models_get_the_long_context_flag(self):
        caps, ctx = P._infer_capabilities("claude-sonnet-5", "anthropic", False)
        assert P.Capability.LONG_CONTEXT in caps and ctx >= 32_768

    def test_a_small_model_does_not_claim_long_context(self):
        caps, ctx = P._infer_capabilities("tinyllama", "ollama", True)
        assert P.Capability.LONG_CONTEXT not in caps and ctx == 8192

    def test_json_mode_is_assumed_everywhere(self):
        """Every backend implemented here supports it one way or another."""
        caps, _ = P._infer_capabilities("anything", "ollama", True)
        assert P.Capability.JSON_MODE in caps


class TestModelInfo:
    def test_satisfies_requires_every_capability(self):
        m = P.ModelInfo("m", "p", 128_000,
                        {P.Capability.LOCAL, P.Capability.JSON_MODE})
        assert m.satisfies([P.Capability.LOCAL])
        assert m.satisfies([P.Capability.LOCAL, P.Capability.JSON_MODE])
        assert not m.satisfies([P.Capability.VISION])

    def test_no_requirements_are_always_satisfied(self):
        assert P.ModelInfo("m", "p").satisfies([])


class TestOllama:
    @pytest.mark.asyncio
    async def test_models_are_parsed(self, capture):
        capture({"models": [{"name": "llama3.2"}, {"name": "qwen2.5:7b"}]})
        models = await P.OllamaProvider().list_models()
        assert [m.id for m in models] == ["llama3.2", "qwen2.5:7b"]
        assert all(m.is_local for m in models)

    @pytest.mark.asyncio
    async def test_generate_uses_the_native_shape(self, capture):
        sent = capture({"response": "hi there"})
        out = await P.OllamaProvider().generate("prompt", "llama3.2",
                                                system="be brief", json_mode=True)
        assert out == "hi there"
        body = sent["json"]
        assert body["model"] == "llama3.2" and body["system"] == "be brief"
        assert body["format"] == "json"          # Ollama's own JSON switch
        assert body["stream"] is False

    @pytest.mark.asyncio
    async def test_an_unreachable_host_names_itself(self, monkeypatch):
        import httpx

        class Boom:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **k): raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Boom())
        with pytest.raises(P.ProviderError, match="Cannot reach Ollama"):
            await P.OllamaProvider("http://nope:1").list_models()


class TestOpenAICompatible:
    @pytest.mark.asyncio
    async def test_models_are_parsed_from_the_data_envelope(self, capture):
        capture({"data": [{"id": "local-model"}]})
        models = await P.OpenAICompatibleProvider("http://localhost:1234/v1").list_models()
        assert models[0].id == "local-model"

    @pytest.mark.asyncio
    async def test_generate_uses_chat_completions(self, capture):
        sent = capture({"choices": [{"message": {"content": "answer"}}]})
        out = await P.OpenAICompatibleProvider("http://x/v1", "sk-key").generate(
            "prompt", "gpt-4o", system="sys", json_mode=True)
        assert out == "answer"
        assert sent["url"].endswith("/chat/completions")
        assert sent["json"]["messages"][0]["role"] == "system"
        assert sent["json"]["response_format"] == {"type": "json_object"}
        assert sent["headers"]["Authorization"] == "Bearer sk-key"

    @pytest.mark.asyncio
    async def test_an_empty_completion_is_an_error_not_an_empty_string(self, capture):
        capture({"choices": []})
        with pytest.raises(P.ProviderError, match="no completion"):
            await P.OpenAICompatibleProvider("http://x/v1").generate("p", "m")

    @pytest.mark.parametrize("url,local", [
        ("http://localhost:1234/v1", True),
        ("http://127.0.0.1:8080/v1", True),
        ("https://api.openai.com/v1", False),
        ("https://openrouter.ai/api/v1", False),
    ])
    def test_loopback_urls_keep_the_local_badge(self, url, local):
        assert P.OpenAICompatibleProvider(url).is_local is local


class TestAnthropic:
    @pytest.mark.asyncio
    async def test_a_missing_key_is_refused_before_any_request(self):
        with pytest.raises(P.ProviderError, match="API key"):
            await P.AnthropicProvider("").list_models()

    @pytest.mark.asyncio
    async def test_the_system_prompt_is_a_top_level_field(self, capture):
        """Anthropic does not take system as a message — the reason for a
        separate adapter rather than reusing the OpenAI one."""
        sent = capture({"content": [{"type": "text", "text": "reply"}]})
        out = await P.AnthropicProvider("sk-ant").generate("prompt", "claude-sonnet-5",
                                                           system="be terse")
        assert out == "reply"
        assert sent["json"]["system"] == "be terse"
        assert all(m["role"] != "system" for m in sent["json"]["messages"])
        assert sent["headers"]["x-api-key"] == "sk-ant"

    @pytest.mark.asyncio
    async def test_text_blocks_are_concatenated(self, capture):
        capture({"content": [{"type": "text", "text": "one "},
                             {"type": "thinking", "text": "ignored"},
                             {"type": "text", "text": "two"}]})
        out = await P.AnthropicProvider("k").generate("p", "claude-sonnet-5")
        assert out == "one two"


class TestBuildProvider:
    @pytest.mark.parametrize("kind,cls", [
        ("ollama", P.OllamaProvider),
        ("anthropic", P.AnthropicProvider),
        ("openai-compatible", P.OpenAICompatibleProvider),
        ("lmstudio", P.OpenAICompatibleProvider),
    ])
    def test_known_kinds(self, kind, cls):
        assert isinstance(P.build_provider(kind, base_url="http://x/v1"), cls)

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(P.ProviderError, match="Unknown provider"):
            P.build_provider("telepathy")

    def test_a_compatible_provider_needs_a_url(self):
        with pytest.raises(P.ProviderError, match="needs a base URL"):
            P.build_provider("openai-compatible")


class TestRouting:
    @pytest.fixture
    def models(self, monkeypatch):
        def _set(*infos):
            async def fake():
                return list(infos)
            monkeypatch.setattr(P, "available_models", fake)
        return _set

    @pytest.mark.asyncio
    async def test_local_is_preferred_over_hosted(self, models):
        """The rule that keeps the app's premise intact."""
        models(
            P.ModelInfo("hosted", "openai", 128_000,
                        {P.Capability.JSON_MODE, P.Capability.LONG_CONTEXT}, False),
            P.ModelInfo("local", "ollama", 8192, {P.Capability.JSON_MODE}, True),
        )
        chosen = await P.route([P.Capability.JSON_MODE])
        assert chosen.id == "local"

    @pytest.mark.asyncio
    async def test_an_explicit_preference_wins(self, models):
        models(
            P.ModelInfo("local", "ollama", 8192, {P.Capability.JSON_MODE}, True),
            P.ModelInfo("hosted", "openai", 128_000, {P.Capability.JSON_MODE}, False),
        )
        chosen = await P.route([P.Capability.JSON_MODE], prefer="hosted")
        assert chosen.id == "hosted"

    @pytest.mark.asyncio
    async def test_a_required_capability_excludes_models_without_it(self, models):
        models(
            P.ModelInfo("small", "ollama", 8192, {P.Capability.LOCAL}, True),
            P.ModelInfo("big", "ollama", 128_000,
                        {P.Capability.LOCAL, P.Capability.LONG_CONTEXT}, True),
        )
        chosen = await P.route([P.Capability.LONG_CONTEXT])
        assert chosen.id == "big"

    @pytest.mark.asyncio
    async def test_larger_context_breaks_a_tie_among_local_models(self, models):
        models(
            P.ModelInfo("small", "ollama", 8192, {P.Capability.LOCAL}, True),
            P.ModelInfo("large", "ollama", 128_000, {P.Capability.LOCAL}, True),
        )
        assert (await P.route([P.Capability.LOCAL])).id == "large"

    @pytest.mark.asyncio
    async def test_nothing_satisfying_returns_none(self, models):
        models(P.ModelInfo("plain", "ollama", 8192, set(), True))
        assert await P.route([P.Capability.VISION]) is None

    @pytest.mark.asyncio
    async def test_local_only_never_selects_a_hosted_model(self, models):
        models(P.ModelInfo("hosted", "openai", 128_000, {P.Capability.JSON_MODE}, False))
        assert await P.route([P.Capability.LOCAL]) is None


class TestApi:
    def test_providers_endpoint_reports_locality(self, client):
        r = client.get("/api/v1/providers")
        assert r.status_code == 200
        body = r.json()
        assert any(p["name"] == "ollama" and p["is_local"] for p in body["providers"])
        assert "local" in body["capabilities"]

    def test_models_endpoint_responds(self, client):
        assert client.get("/api/v1/providers/models").status_code == 200

    def test_route_rejects_an_unknown_capability(self, client):
        r = client.post("/api/v1/providers/route", json={"required": ["telepathy"]})
        assert r.status_code == 400
