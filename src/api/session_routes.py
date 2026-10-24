"""Work session API — durable sessions and their permission posture."""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.db.session_models import PERMISSION_MODES
from src.services import session_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class SessionCreate(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=300)
    kind: str = "general"
    permission_mode: str = "ask"
    workspace_roots: List[str] = Field(default_factory=list)
    model: Optional[str] = None


class ModeUpdate(BaseModel):
    permission_mode: str


class CheckpointUpdate(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)


class FinishRequest(BaseModel):
    ok: bool = True
    error: str = ""


@router.get("/meta")
async def meta():
    return {
        "modes": [
            {"id": "ask", "label": "Ask every time",
             "blurb": "Every consequential action raises an Inbox item."},
            {"id": "unattended", "label": "Unattended",
             "blurb": "Low-risk actions proceed automatically. Medium and high still ask."},
            {"id": "readonly", "label": "Read-only",
             "blurb": "Nothing that writes, sends or executes is permitted — grants included."},
        ],
    }


@router.get("/project/{project_id}")
async def list_sessions(project_id: str, state: Optional[str] = None,
                        db: DatabaseManager = Depends(get_db)):
    return {"sessions": svc.list_sessions(db, project_id, state)}


@router.post("/reconcile/{project_id}")
async def reconcile(project_id: str, db: DatabaseManager = Depends(get_db)):
    """Suspend sessions left 'active' by a restart, rather than failing them."""
    return svc.reconcile(db, project_id)


@router.post("")
async def create(req: SessionCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create(db, req.project_id, req.title, req.kind,
                          req.permission_mode, req.workspace_roots, req.model)
    except svc.SessionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}")
async def get_session(session_id: str, db: DatabaseManager = Depends(get_db)):
    out = svc.get(db, session_id)
    if not out:
        raise HTTPException(status_code=404, detail="Session not found")
    return out


@router.get("/{session_id}/events")
async def get_events(session_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.get(db, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"events": svc.events(db, session_id)}


def _act(fn, *args):
    try:
        return fn(*args)
    except svc.SessionError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/{session_id}/suspend")
async def suspend(session_id: str, db: DatabaseManager = Depends(get_db)):
    return _act(svc.suspend, db, session_id)


@router.post("/{session_id}/resume")
async def resume(session_id: str, db: DatabaseManager = Depends(get_db)):
    return _act(svc.resume, db, session_id)


@router.post("/{session_id}/finish")
async def finish(session_id: str, req: FinishRequest,
                 db: DatabaseManager = Depends(get_db)):
    return _act(svc.finish, db, session_id, req.ok, req.error)


@router.put("/{session_id}/mode")
async def set_mode(session_id: str, req: ModeUpdate,
                   db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_mode(db, session_id, req.permission_mode)
    except svc.SessionError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.put("/{session_id}/checkpoint")
async def save_checkpoint(session_id: str, req: CheckpointUpdate,
                          db: DatabaseManager = Depends(get_db)):
    return _act(svc.checkpoint, db, session_id, req.state)
