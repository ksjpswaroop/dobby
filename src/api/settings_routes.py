"""
Settings & Model Management API

Powers the desktop app's Settings screen:
- View / update the active Ollama model, host and verification threshold
- List, pull and remove Ollama models
- Report app / backend / Ollama versions and connectivity
"""

import platform
import sys

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.settings.store import APP_VERSION, get_settings_store

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["Settings"])


# ============================================================================
# Schemas
# ============================================================================
class SettingsResponse(BaseModel):
    ollama_host: str
    model: str
    theme: str
    verification_threshold: float
    app_version: str

    search_provider: str = "none"
    searxng_url: str = ""
    wigolo_url: str = ""
    wigolo_token: str = ""
    symbolica_url: str = ""

    # API keys are deliberately absent from the response. The UI only ever needs
    # to know whether one is set, not what it is, so a stored secret is never
    # echoed back over HTTP.
    tavily_key_set: bool = False
    brave_key_set: bool = False
    symbolica_key_set: bool = False

    @classmethod
    def from_settings(cls, s) -> "SettingsResponse":
        d = s.to_dict()
        return cls(
            **{k: v for k, v in d.items() if k in cls.model_fields},
            tavily_key_set=bool(d.get("tavily_api_key")),
            brave_key_set=bool(d.get("brave_api_key")),
            symbolica_key_set=bool(d.get("symbolica_api_key")),
        )


class SettingsUpdate(BaseModel):
    ollama_host: str | None = None
    model: str | None = None
    theme: str | None = None
    verification_threshold: float | None = Field(default=None, ge=0, le=100)

    # Research web search. `search_provider` is validated against the provider
    # registry so a typo cannot silently disable search.
    search_provider: str | None = None
    searxng_url: str | None = None
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    wigolo_url: str | None = None
    wigolo_token: str | None = None

    # Optional symbolic reasoning engine.
    symbolica_url: str | None = None
    symbolica_api_key: str | None = None

    @field_validator("search_provider")
    @classmethod
    def _known_provider(cls, v: str | None) -> str | None:
        from src.services.research_search import PROVIDERS

        if v is not None and v not in PROVIDERS:
            raise ValueError(f"Unknown search provider. Choose one of: {', '.join(PROVIDERS)}")
        return v


class ModelInfo(BaseModel):
    name: str
    size: int | None = None
    parameter_size: str | None = None
    family: str | None = None
    modified_at: str | None = None
    active: bool = False


class PullModelRequest(BaseModel):
    name: str


class SystemInfo(BaseModel):
    app_version: str
    python_version: str
    platform: str
    ollama_host: str
    ollama_reachable: bool
    ollama_version: str | None = None
    active_model: str


# ============================================================================
# Settings
# ============================================================================
@router.get("/settings", response_model=SettingsResponse)
async def get_settings_endpoint():
    s = get_settings_store().load()
    return SettingsResponse.from_settings(s)


@router.put("/settings", response_model=SettingsResponse)
async def update_settings_endpoint(update: SettingsUpdate):
    s = get_settings_store().update(**update.model_dump(exclude_none=True))
    return SettingsResponse.from_settings(s)


# ============================================================================
# Models
# ============================================================================
@router.get("/models", response_model=list[ModelInfo])
async def list_models():
    """List models installed on the configured Ollama host."""
    s = get_settings_store().load()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{s.ollama_host}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.warning("list_models_failed", error=str(e))
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Ollama at {s.ollama_host}. Is it running? ({e})",
        )

    models: list[ModelInfo] = []
    for m in data.get("models", []):
        details = m.get("details", {}) or {}
        name = m.get("name", "")
        models.append(
            ModelInfo(
                name=name,
                size=m.get("size"),
                parameter_size=details.get("parameter_size"),
                family=details.get("family"),
                modified_at=m.get("modified_at"),
                active=(name == s.model or name.split(":")[0] == s.model),
            )
        )
    return models


@router.post("/models/pull")
async def pull_model(req: PullModelRequest):
    """Pull (download) a model onto the configured Ollama host."""
    s = get_settings_store().load()
    last_status = "started"
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{s.ollama_host}/api/pull", json={"name": req.name}
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        import json as _json

                        payload = _json.loads(line)
                        if payload.get("error"):
                            raise HTTPException(status_code=502, detail=payload["error"])
                        last_status = payload.get("status", last_status)
                    except ValueError:
                        continue
    except httpx.HTTPError as e:
        logger.warning("pull_model_failed", model=req.name, error=str(e))
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Ollama at {s.ollama_host}. Is it running? ({e})",
        )

    logger.info("model_pulled", model=req.name, status=last_status)
    return {"success": True, "model": req.name, "status": last_status}


@router.delete("/models/{name}")
async def delete_model(name: str):
    """Remove a model from the configured Ollama host."""
    s = get_settings_store().load()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                "DELETE", f"{s.ollama_host}/api/delete", json={"name": name}
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("delete_model_failed", model=name, error=str(e))
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach Ollama at {s.ollama_host}. Is it running? ({e})",
        )
    return {"success": True, "model": name}


# ============================================================================
# System info
# ============================================================================
@router.get("/system/info", response_model=SystemInfo)
async def system_info():
    s = get_settings_store().load()
    reachable = False
    version = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{s.ollama_host}/api/version")
            if resp.status_code == 200:
                reachable = True
                version = resp.json().get("version")
    except httpx.HTTPError:
        reachable = False

    return SystemInfo(
        app_version=APP_VERSION,
        python_version=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()}",
        ollama_host=s.ollama_host,
        ollama_reachable=reachable,
        ollama_version=version,
        active_model=s.model,
    )
