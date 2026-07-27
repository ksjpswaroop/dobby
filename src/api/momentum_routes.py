"""Daily streak & momentum API (100-Day Roadmap, Day 5)."""

from typing import Optional

from fastapi import APIRouter, Depends

from src.db.schema import DatabaseManager
from src.services import momentum_service as svc

router = APIRouter(prefix="/api/v1/momentum", tags=["Momentum"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


@router.get("/project/{project_id}")
async def get_momentum(project_id: str, tz_offset_minutes: Optional[int] = None,
                       db: DatabaseManager = Depends(get_db)):
    """Current streak plus a 14-day sparkline.

    `tz_offset_minutes` is the client's offset from UTC (positive east of
    Greenwich, i.e. the negation of JavaScript's `getTimezoneOffset()`).
    Omitted, the server's own local timezone is used.
    """
    return svc.get_momentum(db, project_id, tz_offset_minutes)
