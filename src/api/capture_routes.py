"""Capture++ API — URL, email, OCR, bulk import, meeting notes (Phase 4)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import capture_service as svc

router = APIRouter(prefix="/api/v1/capture", tags=["Capture"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class UrlImport(BaseModel):
    project_id: str
    url: str


class EmailImport(BaseModel):
    project_id: str
    raw: str


class ImageImport(BaseModel):
    project_id: str
    path: str


class BulkImport(BaseModel):
    project_id: str
    text: str
    format: str = "markdown"
    dry_run: bool = False


class NotesExtract(BaseModel):
    project_id: str
    notes: str
    model: str = ""


class AcceptItems(BaseModel):
    project_id: str
    items: List[Dict[str, Any]]


class MergeIdeas(BaseModel):
    keep_id: str
    merge_ids: List[str]


@router.get("/meta")
async def meta():
    return {"formats": list(svc.PARSERS), "ocr": svc.ocr_capabilities(),
            "duplicate_threshold": svc.DUPLICATE_THRESHOLD}


@router.get("/templates")
async def templates():
    return {"templates": svc.list_templates()}


@router.post("/url")
async def import_url(req: UrlImport, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.import_url(db, req.project_id, req.url)
    except svc.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/email")
async def import_email(req: EmailImport, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.import_email(db, req.project_id, req.raw)
    except svc.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/image")
async def import_image(req: ImageImport, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.import_image(db, req.project_id, req.path)
    except svc.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk")
async def bulk_import(req: BulkImport, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.bulk_import(db, req.project_id, req.text, req.format, req.dry_run)
    except svc.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/notes/extract")
async def extract_notes(req: NotesExtract, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.extract_action_items(db, req.project_id, req.notes, req.model)
    except svc.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/notes/accept")
async def accept_notes(req: AcceptItems, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.accept_action_items(db, req.project_id, req.items)
    except svc.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/duplicates/{project_id}")
async def duplicates(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"pairs": svc.find_duplicates(db, project_id)}


@router.post("/merge")
async def merge(req: MergeIdeas, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.merge_ideas(db, req.keep_id, req.merge_ids)
    except svc.CaptureError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))
