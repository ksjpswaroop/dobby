"""Verification reporting, custom rules, citations, auto-fix (Phase 9)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import quality_service as svc

router = APIRouter(prefix="/api/v1/quality", tags=["Quality"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class RuleSet(BaseModel):
    project_id: str
    rules: List[Dict[str, Any]] = Field(default_factory=list)


class RunRules(BaseModel):
    rules: List[Dict[str, Any]] = Field(default_factory=list)


class ApplyFixes(BaseModel):
    kinds: List[str]


@router.get("/meta")
async def meta():
    return {"rule_kinds": list(svc.RULE_KINDS), "severities": list(svc.SEVERITIES),
            "fixes": [{"kind": k, "label": v[1]} for k, v in svc.FIXES.items()]}


@router.get("/report/{node_id}")
async def report(node_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.verification_report(db, node_id)
    except svc.QualityError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/rules/{project_id}")
async def get_rules(project_id: str):
    return {"rules": svc.get_rules(project_id)}


@router.post("/rules")
async def save_rules(req: RuleSet, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.save_rules(db, req.project_id, req.rules)
    except svc.QualityError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rules/run/{node_id}")
async def run_rules(node_id: str, req: RunRules,
                    db: DatabaseManager = Depends(get_db)):
    try:
        return svc.run_custom_rules(db, node_id, req.rules)
    except svc.QualityError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/citations/{node_id}")
async def citations(node_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.check_citations(db, node_id)
    except svc.QualityError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/fixes/{node_id}")
async def suggest_fixes(node_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.suggest_fixes(db, node_id)
    except svc.QualityError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/fixes/{node_id}")
async def apply_fixes(node_id: str, req: ApplyFixes,
                      db: DatabaseManager = Depends(get_db)):
    try:
        return svc.apply_fixes(db, node_id, req.kinds)
    except svc.QualityError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))
