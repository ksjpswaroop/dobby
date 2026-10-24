"""Activity Timeline API — a unified, reverse-chronological feed (100-Day Roadmap, Day 7)."""

from typing import Optional

from fastapi import APIRouter, Depends

from src.db.schema import DatabaseManager
from src.services import timeline_service as svc

router = APIRouter(prefix="/api/v1/timeline", tags=["Timeline"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


@router.get("/meta")
async def meta():
    return {"categories": list(svc.CATEGORIES)}


@router.get("/project/{project_id}")
async def list_timeline(project_id: str, category: Optional[str] = None,
                        cursor: Optional[str] = None, limit: int = 30,
                        db: DatabaseManager = Depends(get_db)):
    return svc.list_events(db, project_id, category, cursor, min(limit, 100))
