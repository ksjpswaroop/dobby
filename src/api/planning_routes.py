"""Planning & PM API (100-Day Roadmap, Phase 5: Days 41-50)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.planning_models import BOARD_COLUMNS, ESTIMATE_UNITS, SPRINT_STATES
from src.db.schema import DatabaseManager
from src.services import delivery_analytics as analytics
from src.services import planning_service as svc
from src.services import wbs_service

router = APIRouter(prefix="/api/v1/planning", tags=["Planning"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class MoveCard(BaseModel):
    to_column: str
    order_index: Optional[int] = None


class BlockerCreate(BaseModel):
    project_id: str
    feature_id: str
    blocked_by_id: str
    note: str = ""


class EstimateSet(BaseModel):
    estimate: float
    unit: str = "points"


class SprintCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    starts_on: str
    ends_on: str
    goal: str = ""
    capacity: float = 0.0


class StateSet(BaseModel):
    state: str


class AssignSprint(BaseModel):
    sprint_id: Optional[str] = None


class AssignMilestone(BaseModel):
    milestone_id: Optional[str] = None


class MilestoneCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    due_on: str
    description: str = ""


class PlanCommit(BaseModel):
    plan_date: str
    items: List[Dict[str, Any]] = Field(default_factory=list)


class ObjectiveCreate(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    period: str = ""


class KeyResultCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    target: float = 100.0


class WBSAccept(BaseModel):
    project_id: str
    subtasks: List[Dict[str, Any]]


@router.get("/meta")
async def meta():
    return {"columns": list(BOARD_COLUMNS), "sprint_states": list(SPRINT_STATES),
            "estimate_units": list(ESTIMATE_UNITS)}


# --- Board (D41, D44) --------------------------------------------------------
@router.get("/board/{project_id}")
async def board(project_id: str, sprint_id: Optional[str] = None,
                db: DatabaseManager = Depends(get_db)):
    return svc.get_board(db, project_id, sprint_id)


@router.post("/board/{feature_id}/move")
async def move_card(feature_id: str, req: MoveCard,
                    db: DatabaseManager = Depends(get_db)):
    try:
        return svc.move_card(db, feature_id, req.to_column, req.order_index)
    except svc.PlanningError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/ready/{project_id}")
async def ready(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"features": svc.ready_features(db, project_id)}


# --- Blockers (D44) ----------------------------------------------------------
@router.get("/blockers/{project_id}")
async def list_blockers(project_id: str, feature_id: Optional[str] = None,
                        db: DatabaseManager = Depends(get_db)):
    return svc.list_blockers(db, project_id, feature_id)


@router.post("/blockers")
async def add_blocker(req: BlockerCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.add_blocker(db, req.project_id, req.feature_id,
                               req.blocked_by_id, req.note)
    except svc.PlanningError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/blockers/{blocker_id}")
async def remove_blocker(blocker_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.remove_blocker(db, blocker_id):
        raise HTTPException(status_code=404, detail="Blocker not found")
    return {"success": True}


# --- Estimates (D45) ---------------------------------------------------------
@router.post("/estimate/{feature_id}")
async def set_estimate(feature_id: str, req: EstimateSet,
                       db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_estimate(db, feature_id, req.estimate, req.unit)
    except svc.PlanningError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


# --- Sprints (D43) -----------------------------------------------------------
@router.get("/sprints/{project_id}")
async def list_sprints(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"sprints": svc.list_sprints(db, project_id)}


@router.post("/sprints")
async def create_sprint(req: SprintCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_sprint(db, req.project_id, req.name, req.starts_on,
                                 req.ends_on, req.goal, req.capacity)
    except svc.PlanningError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sprints/{sprint_id}/state")
async def set_sprint_state(sprint_id: str, req: StateSet,
                           db: DatabaseManager = Depends(get_db)):
    try:
        return svc.set_sprint_state(db, sprint_id, req.state)
    except svc.PlanningError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/sprints/summary/{sprint_id}")
async def sprint_summary(sprint_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.sprint_summary(db, sprint_id)
    except svc.PlanningError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/assign-sprint/{feature_id}")
async def assign_sprint(feature_id: str, req: AssignSprint,
                        db: DatabaseManager = Depends(get_db)):
    try:
        return svc.assign_to_sprint(db, feature_id, req.sprint_id)
    except svc.PlanningError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Milestones + timeline (D42) ---------------------------------------------
@router.get("/milestones/{project_id}")
async def list_milestones(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"milestones": svc.list_milestones(db, project_id)}


@router.post("/milestones")
async def create_milestone(req: MilestoneCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_milestone(db, req.project_id, req.name, req.due_on,
                                    req.description)
    except svc.PlanningError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/assign-milestone/{feature_id}")
async def assign_milestone(feature_id: str, req: AssignMilestone,
                           db: DatabaseManager = Depends(get_db)):
    try:
        return svc.assign_to_milestone(db, feature_id, req.milestone_id)
    except svc.PlanningError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/timeline/{project_id}")
async def timeline(project_id: str, db: DatabaseManager = Depends(get_db)):
    return svc.timeline(db, project_id)


# --- Daily plan (D47) --------------------------------------------------------
@router.get("/daily/{project_id}/propose")
async def propose_daily(project_id: str, capacity: float = svc.DEFAULT_DAILY_CAPACITY,
                        db: DatabaseManager = Depends(get_db)):
    return svc.propose_daily_plan(db, project_id, capacity)


@router.get("/daily/{project_id}")
async def get_daily(project_id: str, plan_date: str,
                    db: DatabaseManager = Depends(get_db)):
    plan = svc.get_daily_plan(db, project_id, plan_date)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan for that date")
    return plan


@router.post("/daily/{project_id}")
async def commit_daily(project_id: str, req: PlanCommit,
                       db: DatabaseManager = Depends(get_db)):
    return svc.commit_daily_plan(db, project_id, req.plan_date, req.items)


# --- OKRs (D49) --------------------------------------------------------------
@router.get("/objectives/{project_id}")
async def list_objectives(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"objectives": svc.list_objectives(db, project_id)}


@router.post("/objectives")
async def create_objective(req: ObjectiveCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_objective(db, req.project_id, req.title, req.description,
                                    req.period)
    except svc.PlanningError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/objectives/{objective_id}/key-results")
async def add_key_result(objective_id: str, req: KeyResultCreate,
                         db: DatabaseManager = Depends(get_db)):
    try:
        return svc.add_key_result(db, objective_id, req.title, req.target)
    except svc.PlanningError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/key-results/{key_result_id}/link/{feature_id}")
async def link_kr(key_result_id: str, feature_id: str,
                  db: DatabaseManager = Depends(get_db)):
    try:
        return svc.link_feature_to_kr(db, key_result_id, feature_id)
    except svc.PlanningError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Analytics + weekly ritual (D48, D50) ------------------------------------
@router.get("/analytics/{project_id}")
async def analytics_summary(project_id: str, db: DatabaseManager = Depends(get_db)):
    return analytics.summary(db, project_id)


@router.get("/weekly-review/{project_id}")
async def weekly_review(project_id: str, db: DatabaseManager = Depends(get_db)):
    return analytics.weekly_review(db, project_id)


# --- Work breakdown (D46) ----------------------------------------------------
@router.post("/wbs/{project_id}/{feature_id}/propose")
async def wbs_propose(project_id: str, feature_id: str, model: str = "",
                      db: DatabaseManager = Depends(get_db)):
    try:
        return await wbs_service.propose(db, project_id, feature_id, model)
    except wbs_service.WBSError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/wbs/{parent_id}/accept")
async def wbs_accept(parent_id: str, req: WBSAccept,
                     db: DatabaseManager = Depends(get_db)):
    try:
        return wbs_service.accept(db, req.project_id, parent_id, req.subtasks)
    except wbs_service.WBSError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))
