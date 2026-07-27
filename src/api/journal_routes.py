"""Journal and app-registry API (Work Graph, step 5)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.journal_models import ENTRY_KINDS
from src.db.schema import DatabaseManager
from src.services import journal_service as svc

router = APIRouter(prefix="/api/v1/journal", tags=["Journal"])
apps_router = APIRouter(prefix="/api/v1/apps", tags=["Apps"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class EntryWrite(BaseModel):
    project_id: str
    body: str = Field(..., min_length=1)
    entry_date: Optional[str] = None
    title: str = ""
    kind: str = "reflection"
    highlights: List[str] = Field(default_factory=list)


class AutoDraft(BaseModel):
    entry_date: Optional[str] = None
    save: bool = False


@router.get("/meta")
async def meta():
    return {"kinds": list(ENTRY_KINDS)}


@router.get("/project/{project_id}")
async def list_entries(project_id: str, limit: int = 60,
                       db: DatabaseManager = Depends(get_db)):
    return {"entries": svc.list_entries(db, project_id, limit)}


@router.get("/project/{project_id}/streak")
async def streak(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.streak(db, project_id)


@router.get("/project/{project_id}/{entry_date}")
async def get_entry(project_id: str, entry_date: str, kind: str = "reflection",
                    db: DatabaseManager = Depends(get_db)):
    try:
        e = svc.get(db, project_id, entry_date, kind)
    except svc.JournalError as e_:
        raise HTTPException(status_code=400, detail=str(e_))
    if not e:
        raise HTTPException(status_code=404, detail="No entry for that date")
    return e


@router.post("")
async def write(req: EntryWrite, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.write(db, req.project_id, req.body, req.entry_date,
                         req.title, req.kind, req.highlights)
    except svc.JournalError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/auto/{project_id}")
async def auto(project_id: str, req: AutoDraft,
               db: DatabaseManager = Depends(get_db)):
    try:
        return svc.auto_entry(db, project_id, req.entry_date, req.save)
    except svc.JournalError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{entry_id}")
async def delete(entry_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete(db, entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}


@apps_router.get("/{project_id}")
async def registry(project_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.app_registry(db, project_id)
    except svc.JournalError as e:
        raise HTTPException(status_code=404, detail=str(e))
