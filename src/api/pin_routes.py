"""Pins & Favorites API (100-Day Roadmap, Day 8)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.db.pin_models import ENTITY_TYPES
from src.db.schema import DatabaseManager
from src.services import pin_service as svc

router = APIRouter(prefix="/api/v1/pins", tags=["Pins"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class PinCreate(BaseModel):
    project_id: str
    entity_type: str
    entity_id: str


class PinReorder(BaseModel):
    project_id: str
    pin_ids: List[str]


@router.get("/meta")
async def meta():
    return {"entity_types": list(ENTITY_TYPES)}


@router.get("/project/{project_id}")
async def list_pins(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"pins": svc.list_pins(db, project_id)}


@router.post("")
async def create_pin(req: PinCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.pin(db, req.project_id, req.entity_type, req.entity_id)
    except svc.PinError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{entity_type}/{entity_id}")
async def delete_pin(entity_type: str, entity_id: str, project_id: str,
                     db: DatabaseManager = Depends(get_db)):
    if not svc.unpin(db, project_id, entity_type, entity_id):
        raise HTTPException(status_code=404, detail="Pin not found")
    return {"success": True}


@router.patch("/reorder")
async def reorder_pins(req: PinReorder, db: DatabaseManager = Depends(get_db)):
    try:
        return {"pins": svc.reorder(db, req.project_id, req.pin_ids)}
    except svc.PinError as e:
        raise HTTPException(status_code=400, detail=str(e))
