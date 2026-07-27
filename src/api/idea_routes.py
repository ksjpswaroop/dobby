"""Idea Inbox API — quick-capture and triage (100-Day Roadmap, Days 2-3)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.idea_models import STATUSES
from src.db.schema import DatabaseManager
from src.services import idea_service as svc

router = APIRouter(prefix="/api/v1/ideas", tags=["Ideas"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class IdeaCapture(BaseModel):
    project_id: str
    text: str = Field(..., min_length=1, max_length=4000)


class IdeaTriageBacklog(BaseModel):
    impact_score: int = 5
    effort_score: int = 5
    risk_score: int = 5


@router.get("/meta")
async def meta():
    return {"statuses": list(STATUSES)}


@router.post("")
async def capture(req: IdeaCapture, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.capture(db, req.project_id, req.text)
    except svc.IdeaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/project/{project_id}")
async def list_ideas(project_id: str, status: Optional[str] = None,
                     db: DatabaseManager = Depends(get_db)):
    try:
        return {"ideas": svc.list_ideas(db, project_id, status)}
    except svc.IdeaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{idea_id}")
async def get_idea(idea_id: str, db: DatabaseManager = Depends(get_db)):
    idea = svc.get(db, idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.post("/{idea_id}/triage/backlog")
async def triage_backlog(idea_id: str, req: IdeaTriageBacklog,
                         db: DatabaseManager = Depends(get_db)):
    try:
        return svc.triage_to_backlog(db, idea_id, req.impact_score,
                                     req.effort_score, req.risk_score)
    except svc.IdeaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{idea_id}/triage/research")
async def triage_research(idea_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.triage_to_research(db, idea_id)
    except svc.IdeaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{idea_id}/archive")
async def archive_idea(idea_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.archive(db, idea_id)
    except svc.IdeaError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{idea_id}")
async def delete_idea(idea_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete(db, idea_id):
        raise HTTPException(status_code=404, detail="Idea not found")
    return {"success": True}
