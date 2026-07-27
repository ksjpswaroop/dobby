"""Skills API — Skill Studio's backend (Work Graph, step 3)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.skill_models import (
    APPROVAL_MODES, OUTPUT_ACTIONS, SKILL_STATES, SOURCE_KINDS,
)
from src.db.schema import DatabaseManager
from src.services import skill_service as svc

router = APIRouter(prefix="/api/v1/skills", tags=["Skills"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class SkillCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    prompt: str = Field(..., min_length=1)
    description: str = ""
    goal: str = ""
    expected_output: str = ""
    sources: List[str] = Field(default_factory=list)
    rules: List[str] = Field(default_factory=list)
    approval_mode: str = "manual"
    output_action: str = "return_only"
    output_params: Dict[str, Any] = Field(default_factory=dict)
    max_output_words: int = 0
    local_only: bool = True


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    goal: Optional[str] = None
    expected_output: Optional[str] = None
    sources: Optional[List[str]] = None
    rules: Optional[List[str]] = None
    approval_mode: Optional[str] = None
    output_action: Optional[str] = None
    output_params: Optional[Dict[str, Any]] = None
    max_output_words: Optional[int] = None
    local_only: Optional[bool] = None
    forbid_placeholders: Optional[bool] = None


class RunBody(BaseModel):
    input: str = ""
    simulate: bool = False
    model: str = ""


@router.get("/meta")
async def meta():
    return {
        "sources": list(SOURCE_KINDS), "approval_modes": list(APPROVAL_MODES),
        "output_actions": list(OUTPUT_ACTIONS), "states": list(SKILL_STATES),
        "network_sources": sorted(svc.NETWORK_SOURCES),
    }


@router.get("/project/{project_id}")
async def list_skills(project_id: str, state: Optional[str] = None,
                      db: DatabaseManager = Depends(get_db)):
    try:
        return {"skills": svc.list_skills(db, project_id, state)}
    except svc.SkillError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("")
async def create(req: SkillCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create(db, req.project_id, req.name, req.prompt, req.description,
                          req.goal, req.expected_output, req.sources, req.rules,
                          req.approval_mode, req.output_action, req.output_params,
                          req.max_output_words, req.local_only)
    except svc.SkillError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{skill_id}")
async def get_skill(skill_id: str, db: DatabaseManager = Depends(get_db)):
    sk = svc.get(db, skill_id)
    if not sk:
        raise HTTPException(status_code=404, detail="Skill not found")
    return sk


@router.put("/{skill_id}")
async def update(skill_id: str, req: SkillUpdate,
                 db: DatabaseManager = Depends(get_db)):
    try:
        return svc.update(db, skill_id, **req.model_dump(exclude_none=True))
    except svc.SkillError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/{skill_id}/publish")
async def publish(skill_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.publish(db, skill_id)
    except svc.SkillError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/{skill_id}/fork")
async def fork(skill_id: str, project_id: str,
               db: DatabaseManager = Depends(get_db)):
    try:
        return svc.fork(db, skill_id, project_id)
    except svc.SkillError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{skill_id}")
async def delete(skill_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        if not svc.delete(db, skill_id):
            raise HTTPException(status_code=404, detail="Skill not found")
    except svc.SkillError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.post("/{skill_id}/run")
async def run(skill_id: str, req: RunBody, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.run(db, skill_id, req.input, req.simulate, req.model)
    except svc.SkillError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/{skill_id}/runs")
async def runs(skill_id: str, db: DatabaseManager = Depends(get_db)):
    return {"runs": svc.list_runs(db, skill_id)}
