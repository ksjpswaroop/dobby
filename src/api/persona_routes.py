"""Persona API — built-ins, installs, lifecycle, recommendations."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.personas import registry
from src.personas.manifest import ManifestError

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/personas", tags=["Personas"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class InstallRequest(BaseModel):
    project_id: str = "default-project"
    manifest: str = Field(..., min_length=1, max_length=100_000)


class EnabledUpdate(BaseModel):
    enabled: bool


@router.get("")
async def list_personas():
    return registry.listing()


@router.get("/capabilities")
async def capabilities():
    """The vetted capability catalog a persona may declare."""
    return {"capabilities": registry.capability_catalog()}


@router.get("/active")
async def get_active():
    p = registry.active()
    return p.to_dict() if p else {}


@router.post("/inspect")
async def inspect(req: InstallRequest):
    """What a manifest declares, without installing it."""
    try:
        return registry.inspect(req.manifest)
    except ManifestError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/install")
async def install(req: InstallRequest, db: DatabaseManager = Depends(get_db)):
    try:
        return await registry.install(db, req.project_id, req.manifest)
    except registry.RegistryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{persona_id}/activate")
async def activate(persona_id: str):
    try:
        return registry.set_active(persona_id)
    except registry.RegistryError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.put("/{persona_id}/enabled")
async def set_enabled(persona_id: str, req: EnabledUpdate):
    try:
        return registry.set_enabled(persona_id, req.enabled)
    except registry.RegistryError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/{persona_id}/recommendations")
async def recommendations(persona_id: str):
    try:
        return {"recommendations": await registry.recommendations(persona_id)}
    except registry.RegistryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{persona_id}")
async def uninstall(persona_id: str):
    try:
        if not registry.uninstall(persona_id):
            raise HTTPException(status_code=404, detail="Persona not found")
    except registry.RegistryError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"success": True}
