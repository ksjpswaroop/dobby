"""
Settings Store

Persists user-configurable runtime settings to ``~/.dobby/settings.json`` so the
desktop UI can change the active Ollama model / host without editing code.

Both the API layer and the generation pipelines read the active settings through
``get_settings()`` so a change made in the UI takes effect on the next generation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

APP_VERSION = "2.0.0"

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
DEFAULT_THEME = "system"  # system | light | dark

_SETTINGS_PATH = Path.home() / ".dobby" / "settings.json"


@dataclass
class Settings:
    """User-configurable runtime settings."""

    ollama_host: str = DEFAULT_OLLAMA_HOST
    model: str = DEFAULT_MODEL
    theme: str = DEFAULT_THEME
    verification_threshold: float = 85.0
    app_version: str = APP_VERSION

    # Research web search. Defaults to "none" so the app keeps its promise of
    # making no network calls beyond the local model unless the user opts in.
    # "searxng" can be self-hosted and stays local; tavily/brave send queries
    # to a third party, which the UI states before enabling them.
    search_provider: str = "none"  # none | wigolo | searxng | tavily | brave
    searxng_url: str = ""
    tavily_api_key: str = ""
    brave_api_key: str = ""
    # wigolo runs as a separate local daemon (`wigolo serve`). Keyless on
    # loopback; the token is only needed when it is bound past 127.0.0.1.
    wigolo_url: str = "http://127.0.0.1:3333"
    wigolo_token: str = ""

    # Symbolica — optional symbolic reasoning engine. Empty means the local
    # propositional prover handles everything, which it does completely.
    symbolica_url: str = ""
    symbolica_api_key: str = ""

    # Terminal. The allowlist is EMPTY by default (OW row 53): nothing runs
    # without an explicit human decision until the user opts a program in.
    # Comma-separated program names, never whole command lines.
    shell_allowlist: str = ""
    workspace_root: str = ""

    # Additional model providers. Ollama is always available; these are opt-in.
    # An OpenAI-compatible base_url covers LM Studio, llama.cpp, vLLM, OpenRouter
    # and OpenAI itself — only the URL differs.
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_label: str = ""
    anthropic_api_key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        known = {f: data[f] for f in cls().to_dict().keys() if f in data}
        return cls(**known)


class SettingsStore:
    """Reads/writes settings from a JSON file with in-memory caching."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _SETTINGS_PATH
        self._cache: Optional[Settings] = None

    def load(self) -> Settings:
        if self._cache is not None:
            return self._cache

        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self._cache = Settings.from_dict(data)
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logger.warning("settings_load_failed", error=str(e), path=str(self.path))
                self._cache = Settings()
        else:
            self._cache = Settings()

        # app_version is always authoritative from code, never from disk
        self._cache.app_version = APP_VERSION
        return self._cache

    def save(self, settings: Settings) -> Settings:
        settings.app_version = APP_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(settings.to_dict(), indent=2))
        self._cache = settings
        logger.info("settings_saved", model=settings.model, host=settings.ollama_host)
        return settings

    def update(self, **changes: Any) -> Settings:
        """Apply a partial update and persist. Unknown keys are ignored."""
        current = self.load()
        valid_fields = current.to_dict().keys()
        for key, value in changes.items():
            if value is None:
                continue
            if key in valid_fields and key != "app_version":
                setattr(current, key, value)
        return self.save(current)


_store: Optional[SettingsStore] = None


def get_settings_store() -> SettingsStore:
    """Return the process-wide settings store singleton."""
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store


def get_settings() -> Settings:
    """Convenience accessor for the current settings."""
    return get_settings_store().load()
