"""
Automation API — scheduled work.

Firing is always asynchronous: an automation can take minutes, so `/run`
returns immediately and progress is followed through Logs & Traces like any
other run.
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.automation_models import ACTION_KINDS, TRIGGER_KINDS
from src.db.schema import DatabaseManager
from src.scheduler import cron
from src.services import automation_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/automations", tags=["Automations"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class AutomationCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=200)
    action: str
    trigger: str = "cron"
    cron: str = ""
    run_at: Optional[str] = None
    timezone: str = "UTC"
    action_config: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    max_runs: int = 0


class EnabledUpdate(BaseModel):
    enabled: bool


@router.get("/meta")
async def meta():
    """Action kinds, trigger kinds, and schedule presets, for building the form."""
    return {
        "actions": [
            {"id": "research", "label": "Run research",
             "blurb": "A full five-track research brief on a topic."},
            {"id": "generate", "label": "Generate documents",
             "blurb": "Generate the document set for the top backlog feature."},
            {"id": "verify", "label": "Check review queue",
             "blurb": "Report how many documents are awaiting review."},
            {"id": "digest", "label": "Daily digest",
             "blurb": "What changed in the last 24 hours."},
        ],
        "triggers": list(TRIGGER_KINDS),
        "presets": [
            {"label": "Every weekday at 9am", "cron": "0 9 * * 1-5"},
            {"label": "Every morning", "cron": "@daily"},
            {"label": "Every Monday", "cron": "0 9 * * 1"},
            {"label": "Every hour", "cron": "@hourly"},
            {"label": "Every 15 minutes", "cron": "*/15 * * * *"},
        ],
    }


@router.post("/preview")
async def preview(body: Dict[str, Any]):
    """Validate a cron expression and show when it would next fire."""
    expr = str(body.get("cron") or "")
    tz = str(body.get("timezone") or "UTC")
    try:
        nxt = cron.next_fire(expr, None, tz)
    except cron.CronError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "valid": True,
        "description": cron.describe(expr, tz),
        "next_run": nxt.isoformat() if nxt else None,
        "never": nxt is None,
    }


@router.get("/project/{project_id}")
async def list_automations(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {
        "automations": svc.list_for_project(db, project_id),
        "unread": svc.unread_total(db, project_id),
    }


@router.post("")
async def create_automation(req: AutomationCreate,
                            db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create(
            db, req.project_id, req.name, req.action, req.trigger, req.cron,
            req.run_at, req.timezone, req.action_config, req.description,
            req.max_runs,
        )
    except svc.AutomationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{automation_id}")
async def get_automation(automation_id: str, db: DatabaseManager = Depends(get_db)):
    a = svc.get(db, automation_id)
    if not a:
        raise HTTPException(status_code=404, detail="Automation not found")
    return a


@router.get("/{automation_id}/runs")
async def get_runs(automation_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.get(db, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"runs": svc.list_runs(db, automation_id)}


@router.put("/{automation_id}/enabled")
async def set_enabled(automation_id: str, req: EnabledUpdate,
                      db: DatabaseManager = Depends(get_db)):
    out = svc.set_enabled(db, automation_id, req.enabled)
    if not out:
        raise HTTPException(status_code=404, detail="Automation not found")
    return out


@router.post("/{automation_id}/read")
async def mark_read(automation_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.get(db, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found")
    return svc.mark_read(db, automation_id)


@router.post("/{automation_id}/run")
async def run_now(automation_id: str, background: BackgroundTasks,
                  db: DatabaseManager = Depends(get_db)):
    """Fire an automation immediately, regardless of its schedule."""
    a = svc.get(db, automation_id)
    if not a:
        raise HTTPException(status_code=404, detail="Automation not found")
    if a["is_running"]:
        raise HTTPException(status_code=409, detail="This automation is already running")

    async def _fire():
        try:
            await svc.fire(db, automation_id, source="manual")
        except Exception:
            logger.warning("manual_fire_failed", id=automation_id)

    background.add_task(_fire)
    return {"success": True, "status": "started"}


@router.delete("/{automation_id}")
async def delete_automation(automation_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete(db, automation_id):
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"success": True}
