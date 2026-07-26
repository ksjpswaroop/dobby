"""Inbox & Approvals API — parked asks and standing grants."""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.inbox_models import ASK_KINDS, CAPABILITIES, RISK_LEVELS
from src.db.schema import DatabaseManager
from src.services import inbox_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/inbox", tags=["Inbox"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class AskCreate(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=300)
    kind: str = "approval"
    capability: Optional[str] = None
    target: str = ""
    detail: str = ""
    risk: str = "medium"
    options: List[str] = Field(default_factory=list)


class AskAnswer(BaseModel):
    approved: bool
    answer: str = ""
    # Hours to remember this decision as a standing grant. None = don't.
    remember_hours: Optional[int] = None


class GrantCreate(BaseModel):
    project_id: str
    capability: str
    target: str
    note: str = ""
    hours: Optional[int] = None


@router.get("/meta")
async def meta():
    """Vocabulary for building the UI."""
    return {
        "capabilities": [
            {"id": "shell.execute", "label": "Run a command"},
            {"id": "net.fetch", "label": "Reach a host"},
            {"id": "message.send", "label": "Send a message"},
            {"id": "file.write", "label": "Write outside the project"},
            {"id": "automation.run", "label": "Run a scheduled task"},
        ],
        "kinds": list(ASK_KINDS),
        "risks": list(RISK_LEVELS),
    }


@router.get("/project/{project_id}")
async def list_inbox(project_id: str, state: Optional[str] = None,
                     db: DatabaseManager = Depends(get_db)):
    return {
        "asks": svc.list_asks(db, project_id, state),
        "pending": svc.pending_count(db, project_id),
        "grants": svc.list_grants(db, project_id),
    }


@router.post("/reconcile/{project_id}")
async def reconcile(project_id: str, db: DatabaseManager = Depends(get_db)):
    """Clean up asks stranded by a restart."""
    return svc.reconcile(db, project_id)


@router.post("/asks")
async def create_ask(req: AskCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_ask(
            db, req.project_id, req.title, req.capability, req.target,
            req.kind, req.detail, req.risk, req.options,
        )
    except svc.InboxError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/asks/{ask_id}")
async def get_ask(ask_id: str, db: DatabaseManager = Depends(get_db)):
    a = svc.get_ask(db, ask_id)
    if not a:
        raise HTTPException(status_code=404, detail="Ask not found")
    return a


@router.post("/asks/{ask_id}/answer")
async def answer_ask(ask_id: str, req: AskAnswer,
                     db: DatabaseManager = Depends(get_db)):
    try:
        return svc.answer_ask(db, ask_id, req.approved, req.answer,
                              remember_hours=req.remember_hours)
    except svc.InboxError as e:
        # 409: the ask exists but is no longer answerable.
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/asks/{ask_id}/cancel")
async def cancel_ask(ask_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.cancel_ask(db, ask_id):
        raise HTTPException(status_code=409, detail="This ask is no longer pending")
    return {"success": True}


@router.post("/grants")
async def create_grant(req: GrantCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.grant(db, req.project_id, req.capability, req.target,
                         req.note, req.hours)
    except svc.InboxError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/grants/{grant_id}")
async def revoke_grant(grant_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.revoke_grant(db, grant_id):
        raise HTTPException(status_code=404, detail="Grant not found")
    return {"success": True}
