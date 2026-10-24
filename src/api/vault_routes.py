"""Encryption vault and pipeline builder (D88, D92)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import pipeline_builder as pipes
from src.services import vault_service as vault

router = APIRouter(prefix="/api/v1/vault", tags=["Vault"])
pipeline_router = APIRouter(prefix="/api/v1/pipelines", tags=["Pipelines"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class Passphrase(BaseModel):
    passphrase: str = Field(..., min_length=1)


class Unlock(BaseModel):
    passphrase: Optional[str] = None


class Rotate(BaseModel):
    old_passphrase: str
    new_passphrase: str = Field(..., min_length=10)


@router.get("/status")
async def status():
    return vault.status()


@router.post("/initialise")
async def initialise(req: Passphrase):
    try:
        return vault.initialise(req.passphrase)
    except vault.VaultError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/unlock")
async def unlock(req: Unlock):
    try:
        return vault.unlock(req.passphrase)
    except vault.VaultError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/lock")
async def lock():
    return vault.lock()


@router.post("/protect")
async def protect():
    try:
        return vault.protect_settings()
    except vault.VaultLocked as e:
        raise HTTPException(status_code=423, detail=str(e))
    except vault.VaultError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rotate")
async def rotate(req: Rotate):
    try:
        return vault.rotate(req.old_passphrase, req.new_passphrase)
    except vault.VaultError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/disable")
async def disable(req: Passphrase):
    try:
        return vault.disable(req.passphrase)
    except vault.VaultError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Pipelines (D92) ---------------------------------------------------------
class PipelineSave(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    steps: List[Dict[str, Any]]


class PipelineRun(BaseModel):
    project_id: str
    steps: Optional[List[Dict[str, Any]]] = None
    payload: str = ""
    dry_run: bool = False


@pipeline_router.get("/catalogue")
async def catalogue():
    return pipes.catalogue()


@pipeline_router.get("/{project_id}")
async def list_pipelines(project_id: str):
    return {"pipelines": pipes.list_pipelines(project_id)}


@pipeline_router.post("")
async def save(req: PipelineSave):
    try:
        return pipes.save_pipeline(req.project_id, req.name, req.steps)
    except pipes.PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))


@pipeline_router.delete("/{project_id}/{pipeline_id}")
async def delete(project_id: str, pipeline_id: str):
    if not pipes.delete_pipeline(project_id, pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"success": True}


@pipeline_router.post("/validate")
async def validate(req: PipelineSave):
    try:
        return {"steps": pipes.validate(req.steps), "valid": True}
    except pipes.PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))


@pipeline_router.post("/run")
async def run(req: PipelineRun, db: DatabaseManager = Depends(get_db)):
    if not req.steps:
        raise HTTPException(status_code=400, detail="Provide steps to run")
    try:
        return await pipes.run(db, req.project_id, req.steps, req.payload, req.dry_run)
    except pipes.PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))


@pipeline_router.post("/run/{pipeline_id}")
async def run_saved(pipeline_id: str, req: PipelineRun,
                    db: DatabaseManager = Depends(get_db)):
    try:
        return await pipes.run_saved(db, req.project_id, pipeline_id,
                                     req.payload, req.dry_run)
    except pipes.PipelineError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))
