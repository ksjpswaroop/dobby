"""Time tracking API — what the day actually went on."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.db.time_models import TIME_SOURCES
from src.services import effort
from src.services import time_service as svc

router = APIRouter(prefix="/api/v1/time", tags=["Time"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class StartTimer(BaseModel):
    project_id: str
    feature_id: Optional[str] = None
    note: str = ""


class LogTime(BaseModel):
    project_id: str
    minutes: int = Field(..., gt=0)
    feature_id: Optional[str] = None
    note: str = ""
    when: Optional[str] = None


@router.get("/meta")
async def meta():
    return {"sources": list(TIME_SOURCES),
            "minutes_per_point": effort.minutes_per_point(),
            "max_session_minutes": svc.MAX_SESSION_MINUTES}


@router.get("/running/{project_id}")
async def running(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"entry": svc.running(db, project_id)}


@router.post("/start")
async def start(req: StartTimer, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.start(db, req.project_id, req.feature_id, req.note)
    except svc.TimeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/stop/{project_id}")
async def stop(project_id: str, db: DatabaseManager = Depends(get_db)):
    entry = svc.stop(db, project_id)
    if not entry:
        raise HTTPException(status_code=409, detail="No timer is running")
    return entry


@router.post("/log")
async def log(req: LogTime, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.log(db, req.project_id, req.minutes, req.feature_id,
                       req.note, req.when)
    except svc.TimeError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/entries/{project_id}")
async def entries(project_id: str, feature_id: Optional[str] = None,
                  days: int = 30, db: DatabaseManager = Depends(get_db)):
    return {"entries": svc.list_entries(db, project_id, feature_id, days)}


@router.get("/spent/{feature_id}")
async def spent(feature_id: str, db: DatabaseManager = Depends(get_db)):
    minutes = svc.spent_on(db, feature_id)
    return {"feature_id": feature_id, "minutes": minutes,
            "human": effort.humanise(minutes)}


@router.get("/day/{project_id}")
async def day(project_id: str, on: Optional[str] = None,
              db: DatabaseManager = Depends(get_db)):
    try:
        return svc.day_summary(db, project_id, on)
    except svc.TimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/weeks/{project_id}")
async def weeks(project_id: str, weeks: int = 4,
                db: DatabaseManager = Depends(get_db)):
    return svc.week_summary(db, project_id, weeks)


@router.delete("/{entry_id}")
async def delete(entry_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete(db, entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}
