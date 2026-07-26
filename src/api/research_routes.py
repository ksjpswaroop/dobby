"""
Research API — the stage that runs before Create.

A brief is created first and executed second, deliberately: research takes
minutes, so the client gets an id immediately and follows progress over the
existing `/runs/stream` SSE channel rather than holding a request open.
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.research_models import TRACK_KINDS, TRACK_LABELS
from src.db.schema import DatabaseManager
from src.services import research_search as search_svc
from src.services import research_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/research", tags=["Research"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class BriefCreate(BaseModel):
    project_id: str
    topic: str = Field(..., min_length=1, max_length=500)
    context: str = ""
    attachment_ids: List[str] = Field(default_factory=list)


class FeatureItem(BaseModel):
    title: str
    description: str = ""
    impact: float = 5
    effort: float = 5
    risk: float = 5


class AcceptFeatures(BaseModel):
    features: List[FeatureItem]


@router.get("/tracks")
async def list_tracks():
    """The fixed research tracks, for rendering the UI before anything runs."""
    return {"tracks": [{"kind": k, "label": TRACK_LABELS[k]} for k in TRACK_KINDS]}


@router.get("/providers")
async def list_providers():
    """Search providers and whether each one leaves the machine."""
    from src.settings import get_settings

    s = get_settings()
    return {
        "providers": [
            {"id": p, "remote": p in search_svc.REMOTE_PROVIDERS}
            for p in search_svc.PROVIDERS
        ],
        "active": getattr(s, "search_provider", "none") or "none",
    }


@router.get("/project/{project_id}")
async def list_briefs(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"briefs": svc.list_briefs(db, project_id)}


@router.post("")
async def create_brief(req: BriefCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_brief(db, req.project_id, req.topic, req.context,
                                req.attachment_ids)
    except svc.ResearchError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{brief_id}")
async def get_brief(brief_id: str, db: DatabaseManager = Depends(get_db)):
    brief = svc.get_brief(db, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Research brief not found")
    return brief


@router.delete("/{brief_id}")
async def delete_brief(brief_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_brief(db, brief_id):
        raise HTTPException(status_code=404, detail="Research brief not found")
    return {"success": True}


@router.post("/{brief_id}/run")
async def run_brief(brief_id: str, background: BackgroundTasks,
                    db: DatabaseManager = Depends(get_db)):
    """Kick off research. Returns immediately; follow progress on /runs/stream."""
    brief = svc.get_brief(db, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail="Research brief not found")
    if brief["status"] in ("planning", "researching", "synthesizing"):
        raise HTTPException(status_code=409, detail="This research is already running")

    async def _run():
        try:
            await svc.run_brief(db, brief_id)
        except Exception:
            # run_brief already recorded the failure on the brief and the run;
            # swallowing here keeps a background crash out of the server log as
            # an unhandled task exception.
            logger.warning("research_background_failed", brief_id=brief_id)

    background.add_task(_run)
    return {"success": True, "brief_id": brief_id, "status": "started"}


@router.post("/{brief_id}/features")
async def propose_features(brief_id: str, db: DatabaseManager = Depends(get_db)):
    """Candidate backlog features from the research. Proposes only."""
    try:
        return {"features": await svc.propose_features(db, brief_id)}
    except svc.ResearchError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{brief_id}/features/accept")
async def accept_features(brief_id: str, req: AcceptFeatures,
                          db: DatabaseManager = Depends(get_db)):
    """Write accepted proposals into the feature backlog."""
    try:
        return svc.accept_features(db, brief_id,
                                   [f.model_dump() for f in req.features])
    except svc.ResearchError as e:
        raise HTTPException(status_code=404, detail=str(e))
