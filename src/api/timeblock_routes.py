"""Time-blocked planning API (Work Graph, step 4)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import timeblock_service as svc

router = APIRouter(prefix="/api/v1/timeblocks", tags=["Time blocks"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class ShapeOverrides(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    deep_work_start: Optional[str] = None
    deep_work_end: Optional[str] = None
    lunch_start: Optional[str] = None
    lunch_end: Optional[str] = None
    buffer_minutes: Optional[int] = None


class PlanRequest(BaseModel):
    capacity: float = 6.0
    plan_date: Optional[str] = None
    shape: Optional[ShapeOverrides] = None


class ScheduleRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    plan_date: Optional[str] = None
    shape: Optional[ShapeOverrides] = None


class CommitRequest(BaseModel):
    plan_date: str
    blocks: List[Dict[str, Any]]


@router.get("/meta")
async def meta():
    return {"default_day": svc.DEFAULT_DAY, "block_kinds": list(svc.BLOCK_KINDS),
            "minutes_per_point": svc.MINUTES_PER_POINT}


@router.post("/plan/{project_id}")
async def plan_day(project_id: str, req: PlanRequest,
                   db: DatabaseManager = Depends(get_db)):
    try:
        return svc.plan_day(db, project_id, req.capacity, req.plan_date,
                            req.shape.model_dump(exclude_none=True) if req.shape else None)
    except svc.TimeblockError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/schedule")
async def schedule(req: ScheduleRequest):
    try:
        return svc.build_schedule(req.items, req.plan_date,
                                  req.shape.model_dump(exclude_none=True) if req.shape else None)
    except svc.TimeblockError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/commit/{project_id}")
async def commit(project_id: str, req: CommitRequest,
                 db: DatabaseManager = Depends(get_db)):
    return svc.commit_day(db, project_id, req.plan_date, req.blocks)
