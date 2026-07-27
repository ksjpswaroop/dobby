"""Decisions API — the forks work waits behind (Work Graph, step 1)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.decision_models import DECISION_STATES, LINK_TYPES
from src.db.schema import DatabaseManager
from src.services import decision_service as svc

router = APIRouter(prefix="/api/v1/decisions", tags=["Decisions"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class DecisionCreate(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=300)
    question: str = ""
    due_on: Optional[str] = None
    options: List[Dict[str, str]] = Field(default_factory=list)


class DecisionUpdate(BaseModel):
    title: Optional[str] = None
    question: Optional[str] = None
    due_on: Optional[str] = None


class OptionCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    note: str = ""


class DecideBody(BaseModel):
    option_id: str
    rationale: str = ""


class SupersedeBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    question: str = ""
    due_on: Optional[str] = None
    options: List[Dict[str, str]] = Field(default_factory=list)


class LinkBody(BaseModel):
    entity_type: str
    entity_id: str
    blocking: bool = True


@router.get("/meta")
async def meta():
    return {"states": list(DECISION_STATES), "link_types": list(LINK_TYPES),
            "due_soon_days": svc.DUE_SOON_DAYS}


@router.get("/project/{project_id}")
async def list_decisions(project_id: str, status: Optional[str] = None,
                         db: DatabaseManager = Depends(get_db)):
    try:
        return {"decisions": svc.list_decisions(db, project_id, status)}
    except svc.DecisionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/project/{project_id}/summary")
async def summary(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.pending_summary(db, project_id)


@router.get("/blocking/{project_id}/{entity_type}/{entity_id}")
async def blockers_for(project_id: str, entity_type: str, entity_id: str,
                       db: DatabaseManager = Depends(get_db)):
    return {"decisions": svc.blockers_for(db, project_id, entity_type, entity_id)}


@router.post("")
async def create(req: DecisionCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create(db, req.project_id, req.title, req.question,
                          req.due_on, req.options)
    except svc.DecisionError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{decision_id}")
async def get_decision(decision_id: str, db: DatabaseManager = Depends(get_db)):
    d = svc.get(db, decision_id)
    if not d:
        raise HTTPException(status_code=404, detail="Decision not found")
    return d


@router.put("/{decision_id}")
async def update(decision_id: str, req: DecisionUpdate,
                 db: DatabaseManager = Depends(get_db)):
    try:
        return svc.update(db, decision_id, req.title, req.question, req.due_on)
    except svc.DecisionError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/{decision_id}")
async def delete(decision_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete(db, decision_id):
        raise HTTPException(status_code=404, detail="Decision not found")
    return {"success": True}


@router.post("/{decision_id}/options")
async def add_option(decision_id: str, req: OptionCreate,
                     db: DatabaseManager = Depends(get_db)):
    try:
        return svc.add_option(db, decision_id, req.label, req.note)
    except svc.DecisionError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/options/{option_id}")
async def remove_option(option_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        if not svc.remove_option(db, option_id):
            raise HTTPException(status_code=404, detail="Option not found")
    except svc.DecisionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"success": True}


@router.post("/{decision_id}/decide")
async def decide(decision_id: str, req: DecideBody,
                 db: DatabaseManager = Depends(get_db)):
    try:
        return svc.decide(db, decision_id, req.option_id, req.rationale)
    except svc.DecisionError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/{decision_id}/supersede")
async def supersede(decision_id: str, req: SupersedeBody,
                    db: DatabaseManager = Depends(get_db)):
    try:
        return svc.supersede(db, decision_id, req.title, req.question,
                             req.due_on, req.options)
    except svc.DecisionError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/{decision_id}/link")
async def link(decision_id: str, req: LinkBody,
               db: DatabaseManager = Depends(get_db)):
    try:
        return svc.link(db, decision_id, req.entity_type, req.entity_id, req.blocking)
    except svc.DecisionError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/links/{link_id}")
async def unlink(link_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.unlink(db, link_id):
        raise HTTPException(status_code=404, detail="Link not found")
    return {"success": True}
