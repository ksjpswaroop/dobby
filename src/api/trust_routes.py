"""Quality & trust API — trash, backup, consistency, batch ops (Phase 9)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.db.trust_models import BATCH_OPERATIONS
from src.services import trust_service as svc

router = APIRouter(prefix="/api/v1/trust", tags=["Trust"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class BatchRun(BaseModel):
    project_id: str
    operation: str
    target_ids: List[str]
    params: Dict[str, Any] = Field(default_factory=dict)


class ImportArchive(BaseModel):
    archive: Dict[str, Any]
    new_project_name: str = ""


@router.get("/meta")
async def meta():
    return {"operations": list(BATCH_OPERATIONS)}


# --- Trash (D90) -------------------------------------------------------------
@router.get("/trash/{project_id}")
async def list_trash(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"items": svc.list_trash(db, project_id)}


@router.delete("/documents/{node_id}")
async def trash_document(node_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.trash_document(db, node_id)
    except svc.TrustError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/features/{feature_id}")
async def trash_feature(feature_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.trash_feature(db, feature_id)
    except svc.TrustError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/ideas/{idea_id}")
async def trash_idea(idea_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.trash_idea(db, idea_id)
    except svc.TrustError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/trash/{trash_id}/restore")
async def restore(trash_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.restore(db, trash_id)
    except svc.TrustError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/trash/{project_id}/empty")
async def empty_trash(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"deleted": svc.empty_trash(db, project_id)}


# --- Backup (D87) ------------------------------------------------------------
@router.get("/export/{project_id}")
async def export_project(project_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.export_project(db, project_id)
    except svc.TrustError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/import")
async def import_project(req: ImportArchive, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.import_project(db, req.archive, req.new_project_name)
    except svc.TrustError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Consistency (D84) -------------------------------------------------------
@router.post("/consistency/{project_id}")
async def check_consistency(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.check_consistency(db, project_id)


@router.get("/consistency/{project_id}")
async def list_issues(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"issues": svc.list_issues(db, project_id)}


# --- Batch (D86) -------------------------------------------------------------
@router.post("/batch")
async def run_batch(req: BatchRun, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.run_batch(db, req.project_id, req.operation, req.target_ids, req.params)
    except svc.TrustError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/batch/{project_id}")
async def list_jobs(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"jobs": svc.list_jobs(db, project_id)}
