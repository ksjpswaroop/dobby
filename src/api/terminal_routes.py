"""Terminal API — approval-gated command execution."""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import terminal_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/terminal", tags=["Terminal"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class CheckRequest(BaseModel):
    command: str
    project_id: str = "default-project"


class RunRequest(BaseModel):
    project_id: str
    command: str = Field(..., min_length=1, max_length=4000)
    cwd: Optional[str] = None
    timeout: int = svc.DEFAULT_TIMEOUT
    session_id: Optional[str] = None


@router.get("/meta")
async def meta(project_id: str = "default-project"):
    """Allowlist state and workspace, so the UI can explain what will happen."""
    return {
        "allowlist": svc.allowlist(),
        "suggested": svc.SUGGESTED_ALLOWLIST,
        "workspace": str(svc.project_root(project_id)),
        "max_timeout": svc.MAX_TIMEOUT,
    }


@router.post("/check")
async def check(req: CheckRequest, db: DatabaseManager = Depends(get_db)):
    """What would happen if this ran — without running it.

    Consults standing grants as well as the allowlist. Telling the user a
    command "will ask for approval" when a grant would let it through silently
    is worse than saying nothing: it misrepresents what is about to happen.
    """
    from src.services import inbox_service as inbox

    try:
        argv = svc.parse(req.command or "")
    except svc.TerminalError as e:
        raise HTTPException(status_code=400, detail=str(e))

    verdict = svc.classify(argv)
    if verdict["decision"] == "ask":
        grant = inbox.find_grant(db, req.project_id, "shell.execute", verdict["program"])
        if grant:
            verdict = {**verdict, "decision": "allowed",
                       "reason": "covered by a standing permission"}
    return {**verdict, "argv": argv}


@router.post("/run")
async def run(req: RunRequest, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.run(db, req.project_id, req.command, req.cwd, req.timeout,
                             session_id=req.session_id)
    except svc.TerminalError as e:
        raise HTTPException(status_code=400, detail=str(e))
