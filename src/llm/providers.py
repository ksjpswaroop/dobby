"""
Model provider abstraction (OW rows 40, 41, 42 — Next Task 6).

Dobby generates through Ollama and only Ollama. The host is configurable, which
covers anything that impersonates Ollama's API, but a user who wants LM Studio,
vLLM, an OpenAI-compatible gateway, or a hosted model has no route in.

One interface, several backends:

* **ollama** — the default, and the only one that needs no key.
* **openai-compatible** — the format nearly everything speaks: LM Studio,
  llama.cpp's server, vLLM, OpenRouter, Together, and OpenAI itself. One
  implementation covers them all; only `base_url` differs.
* **anthropic** — different enough (system prompt is a top-level field, not a
  message) to warrant its own adapter.

Two things this buys beyond "more providers":

* **Per-session model choice** (OW 41). A caller passes a model and gets that
  model, instead of every request reading one global setting.
* **Capability-aware routing** (OW 42). A caller can say *what it needs* — a
  long context, strict JSON, a local-only model — and get something that
  satisfies it, rather than hard-coding a name that may not be installed.

Local-first is preserved by making it explicit rather than implicit:
`Capability.LOCAL` is a real constraint a caller can demand, and `is_local` is
recorded per provider so the UI can say plainly when a request would leave the
machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

import httpx
import structlog

logger = structlog.get_logger()

DEFAULT_TIMEOUT = 180.0


class Capability(str, Enum):
    """What a caller can require of a model."""

    LOCAL = "local"              # never leaves the machine
    JSON_MODE = "json_mode"      # constrained decoding to valid JSON
    TOOLS = "tools"              # native tool/function calling
    LONG_CONTEXT = "long_context"  # >= 32k tokens
    VISION = "vision"


@dataclass
class ModelInfo:
    id: str
    provider: str
    context_window: int = 8192
    capabilities: set = field(default_factory=set)
    is_local: bool = True

    def satisfies(self, required: Sequence[Capability]) -> bool:
        return all(c in self.capabilities for c in required)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "provider": self.provider,
            "context_window": self.context_window,
            "capabilities": sorted(c.value for c in self.capabilities),
            "is_local": self.is_local,
        }


class ProviderError(Exception):
    """A provider could not be reached or refused the request."""


class Provider:
    """One way of talking to models."""

    name = "base"
    is_local = False

    async def list_models(self) -> List[ModelInfo]:
        raise NotImplementedError

    async def generate(self, prompt: str, model: str, *, system: str = "",
                       max_tokens: int = 2000, temperature: float = 0.7,
                       json_mode: bool = False) -> str:
        raise NotImplementedError

    async def health(self) -> Dict[str, Any]:
        try:
            models = await self.list_models()
            return {"reachable": True, "models": len(models)}
        except ProviderError as e:
            return {"reachable": False, "error": str(e)}


def _infer_capabilities(model_id: str, provider: str, is_local: bool) -> tuple:
    """Best-effort capability guess from a model name and its context size.

    Deliberately conservative: claiming a capability a model lacks produces a
    confusing runtime failure, while missing one only costs a routing option.
    Providers that report real metadata should override this.
    """
    lowered = model_id.lower()
    caps = {Capability.JSON_MODE}          # every backend here supports it
    if is_local:
        caps.add(Capability.LOCAL)

    context = 8192
    if any(k in lowered for k in ("128k", "gpt-4o", "gpt-4-turbo", "claude", "sonnet",
                                  "opus", "haiku", "gemini", "qwen2.5", "llama3.1",
                                  "llama3.2", "mistral-nemo")):
        context = 128_000
    elif any(k in lowered for k in ("32k", "mixtral", "command-r")):
        context = 32_768
    if context >= 32_768:
        caps.add(Capability.LONG_CONTEXT)

    if any(k in lowered for k in ("gpt-4", "claude", "qwen2.5", "llama3.1", "llama3.2",
                                  "mistral", "command-r", "firefunction")):
        caps.add(Capability.TOOLS)
    if any(k in lowered for k in ("vision", "llava", "gpt-4o", "claude-3", "gemini")):
        caps.add(Capability.VISION)
    return caps, context


class OllamaProvider(Provider):
    name = "ollama"
    is_local = True

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def list_models(self) -> List[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Ollama at {self.base_url}: {e}")

        out = []
        for m in data.get("models") or []:
            mid = m.get("name") or ""
            if not mid:
                continue
            caps, ctx = _infer_capabilities(mid, self.name, True)
            out.append(ModelInfo(mid, self.name, ctx, caps, True))
        return out

    async def generate(self, prompt: str, model: str, *, system: str = "",
                       max_tokens: int = 2000, temperature: float = 0.7,
                       json_mode: bool = False) -> str:
        payload: Dict[str, Any] = {
            "model": model, "prompt": prompt, "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/api/generate", json=payload)
                r.raise_for_status()
                return (r.json() or {}).get("response", "")
        except httpx.HTTPError as e:
            raise ProviderError(f"Ollama generation failed: {e}")


class OpenAICompatibleProvider(Provider):
    """Covers LM Studio, llama.cpp, vLLM, OpenRouter, Together, OpenAI itself."""

    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str = "", label: str = "",
                 local: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = label or "openai-compatible"
        # A base_url on loopback is a local runtime, so it keeps the local badge.
        self.is_local = local or any(
            h in self.base_url for h in ("localhost", "127.0.0.1", "0.0.0.0")
        )

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def list_models(self) -> List[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach {self.base_url}: {e}")

        out = []
        for m in (data.get("data") or []):
            mid = m.get("id") or ""
            if not mid:
                continue
            caps, ctx = _infer_capabilities(mid, self.name, self.is_local)
            out.append(ModelInfo(mid, self.name, ctx, caps, self.is_local))
        return out

    async def generate(self, prompt: str, model: str, *, system: str = "",
                       max_tokens: int = 2000, temperature: float = 0.7,
                       json_mode: bool = False) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        payload: Dict[str, Any] = {
            "model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/chat/completions",
                                 json=payload, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"Generation failed at {self.base_url}: {e}")
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("The provider returned no completion.")
        return (choices[0].get("message") or {}).get("content", "")


class AnthropicProvider(Provider):
    """Separate adapter: the system prompt is a top-level field, not a message."""

    name = "anthropic"
    is_local = False

    # The API has no model-listing endpoint, so the current family is declared.
    KNOWN = [
        ("claude-opus-5", 200_000),
        ("claude-sonnet-5", 200_000),
        ("claude-haiku-4-5-20251001", 200_000),
    ]

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    async def list_models(self) -> List[ModelInfo]:
        if not self.api_key:
            raise ProviderError("Add an Anthropic API key to use this provider.")
        out = []
        for mid, ctx in self.KNOWN:
            caps, _ = _infer_capabilities(mid, self.name, False)
            caps.add(Capability.LONG_CONTEXT)
            out.append(ModelInfo(mid, self.name, ctx, caps, False))
        return out

    async def generate(self, prompt: str, model: str, *, system: str = "",
                       max_tokens: int = 2000, temperature: float = 0.7,
                       json_mode: bool = False) -> str:
        if not self.api_key:
            raise ProviderError("Add an Anthropic API key to use this provider.")
        payload: Dict[str, Any] = {
            "model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        if json_mode:
            # No response_format field; instruct instead and let the caller's
            # existing JSON repair handle the rest.
            payload["messages"][0]["content"] += "\n\nRespond with JSON only."
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as c:
                r = await c.post(f"{self.base_url}/v1/messages",
                                 json=payload, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"Anthropic generation failed: {e}")
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


# ---------------------------------------------------------------------------
# Resolution & routing
# ---------------------------------------------------------------------------
def build_provider(kind: str, *, base_url: str = "", api_key: str = "",
                   label: str = "") -> Provider:
    if kind == "ollama":
        return OllamaProvider(base_url or "http://localhost:11434")
    if kind == "anthropic":
        return AnthropicProvider(api_key)
    if kind in ("openai-compatible", "openai", "lmstudio", "vllm", "openrouter"):
        if not base_url:
            raise ProviderError("This provider needs a base URL.")
        return OpenAICompatibleProvider(base_url, api_key, label or kind)
    raise ProviderError(f"Unknown provider: {kind}")


def configured_providers() -> List[Provider]:
    """Every provider the user has set up, Ollama always first."""
    from src.settings import get_settings

    s = get_settings()
    out: List[Provider] = [OllamaProvider(getattr(s, "ollama_host", "") or
                                          "http://localhost:11434")]

    compat_url = getattr(s, "openai_base_url", "") or ""
    if compat_url:
        out.append(OpenAICompatibleProvider(
            compat_url, getattr(s, "openai_api_key", "") or "",
            getattr(s, "openai_label", "") or "openai-compatible"))

    anthropic_key = getattr(s, "anthropic_api_key", "") or ""
    if anthropic_key:
        out.append(AnthropicProvider(anthropic_key))
    return out


async def available_models() -> List[ModelInfo]:
    """Every reachable model across every configured provider."""
    import asyncio

    providers = configured_providers()
    results = await asyncio.gather(
        *(p.list_models() for p in providers), return_exceptions=True
    )
    out: List[ModelInfo] = []
    for provider, result in zip(providers, results):
        if isinstance(result, Exception):
            logger.info("provider_unreachable", provider=provider.name,
                        error=str(result))
            continue
        out.extend(result)
    return out


async def route(required: Optional[Sequence[Capability]] = None,
                prefer: str = "") -> Optional[ModelInfo]:
    """Pick a model that satisfies the required capabilities.

    Preference order: the caller's explicit choice, then local models, then the
    largest context. Local first is the point — a routing layer that quietly
    reaches for a hosted model would undo the app's whole premise.
    """
    required = list(required or [])
    models = await available_models()
    candidates = [m for m in models if m.satisfies(required)]
    if not candidates:
        return None
    if prefer:
        exact = next((m for m in candidates if m.id == prefer), None)
        if exact:
            return exact
    candidates.sort(key=lambda m: (not m.is_local, -m.context_window))
    return candidates[0]


async def generate(prompt: str, *, model: str = "", system: str = "",
                   max_tokens: int = 2000, temperature: float = 0.7,
                   json_mode: bool = False,
                   required: Optional[Sequence[Capability]] = None,
                   use_persona: bool = True) -> str:
    """Generate through whichever provider owns the chosen model.

    This is the per-session entry point (OW 41): pass a model and it is used,
    rather than every call reading one global setting.

    The active persona supplies the system prompt when the caller does not, and
    contributes its own model requirements — that is what makes a persona
    change behaviour rather than just being a label on a settings screen. An
    explicit `system` always wins, so a caller that needs exact control keeps it.
    """
    from src.settings import get_settings

    required = list(required or [])
    if use_persona:
        try:
            from src.personas import registry as personas

            persona = personas.active()
            if persona:
                if not system:
                    system = persona.system_prompt
                for name in persona.model_capabilities:
                    try:
                        cap = Capability(name)
                    except ValueError:
                        continue
                    if cap not in required:
                        required.append(cap)
        except Exception:  # a broken persona must not block generation
            logger.warning("persona_unavailable", exc_info=True)

    target = model or getattr(get_settings(), "model", "") or ""
    chosen = await route(required, prefer=target)
    if not chosen:
        raise ProviderError(
            "No configured model satisfies "
            f"{', '.join(c.value for c in (required or [])) or 'this request'}. "
            "Check Settings → Models."
        )

    for provider in configured_providers():
        if provider.name == chosen.provider:
            return await provider.generate(
                prompt, chosen.id, system=system, max_tokens=max_tokens,
                temperature=temperature, json_mode=json_mode,
            )
    raise ProviderError(f"No provider is configured for {chosen.provider}.")
