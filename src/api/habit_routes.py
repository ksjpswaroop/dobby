"""Habit, delight & retention API (Phase 8: Days 71-80)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.db.schema import DatabaseManager
from src.services import habit_service as svc

router = APIRouter(prefix="/api/v1/habit", tags=["Habit"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class MuteSet(BaseModel):
    categories: List[str]


class FocusConfig(BaseModel):
    focus_minutes: int = 25
    break_minutes: int = 5


@router.get("/meta")
async def meta():
    return {"categories": list(svc.NOTIFICATION_CATEGORIES),
            "badges": svc.BADGES, "focus": svc.focus_config()}


@router.get("/reminder/{project_id}")
async def reminder(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.daily_reminder(db, project_id)


@router.get("/recap/{project_id}")
async def recap(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.weekly_recap(db, project_id)


@router.get("/achievements/{project_id}")
async def achievements(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.achievements(db, project_id)


@router.get("/on-this-day/{project_id}")
async def on_this_day(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.on_this_day(db, project_id)


@router.get("/tray/{project_id}")
async def tray(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.tray_summary(db, project_id)


# Declared BEFORE the generic route: FastAPI matches in declaration order, and
# `{project_id}` happily swallows "default-project.svg" if it goes first.
@router.get("/share-card/{project_id}.svg")
async def share_card_svg(project_id: str, db: DatabaseManager = Depends(get_db)):
    return Response(content=svc.share_card(db, project_id)["svg"],
                    media_type="image/svg+xml")


@router.get("/share-card/{project_id}")
async def share_card(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.share_card(db, project_id)


@router.get("/notifications/{category}")
async def check_notification(category: str):
    try:
        return svc.should_notify(category)
    except svc.HabitError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/notifications/{category}/sent")
async def mark_sent(category: str):
    try:
        svc.should_notify(category)  # validates the category name
        return {"last_sent": svc.mark_notified(category)}
    except svc.HabitError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/notifications/mute")
async def mute(req: MuteSet):
    try:
        return {"muted": svc.set_muted(req.categories)}
    except svc.HabitError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/focus")
async def set_focus(req: FocusConfig):
    try:
        return svc.set_focus_config(req.focus_minutes, req.break_minutes)
    except svc.HabitError as e:
        raise HTTPException(status_code=400, detail=str(e))
