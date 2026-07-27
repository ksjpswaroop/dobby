"""AI Copilot API (100-Day Roadmap, Phase 3: Days 21-30)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.copilot_models import TASK_TYPES
from src.db.schema import DatabaseManager
from src.services import copilot_service as copilot
from src.services import model_routing, model_telemetry, nba_service
from src.services import prioritize_ai, prompt_library

router = APIRouter(prefix="/api/v1/copilot", tags=["Copilot"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class ThreadCreate(BaseModel):
    project_id: Optional[str] = None
    title: str = "New chat"


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    model: str = ""


class RouteSet(BaseModel):
    task_type: str
    model: str = ""


class PromptCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1)
    task_type: str = "other"
    description: str = ""


class PromptUpdate(BaseModel):
    body: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class PromptRender(BaseModel):
    values: Dict[str, str] = Field(default_factory=dict)


class AcceptScores(BaseModel):
    impact: Optional[int] = None
    effort: Optional[int] = None
    risk: Optional[int] = None


@router.get("/meta")
async def meta():
    return {"task_types": list(TASK_TYPES)}


# --- Chat (D21, D26) ---------------------------------------------------------
@router.post("/threads")
async def create_thread(req: ThreadCreate, db: DatabaseManager = Depends(get_db)):
    return copilot.create_thread(db, req.project_id, req.title)


@router.get("/threads")
async def list_threads(project_id: Optional[str] = None, scope: str = "project",
                       db: DatabaseManager = Depends(get_db)):
    return {"threads": copilot.list_threads(db, project_id, scope)}


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, db: DatabaseManager = Depends(get_db)):
    return {"messages": copilot.list_messages(db, thread_id)}


@router.post("/threads/{thread_id}/ask")
async def ask(thread_id: str, req: AskBody, db: DatabaseManager = Depends(get_db)):
    try:
        return await copilot.ask(db, thread_id, req.question, req.model)
    except copilot.CopilotError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str, db: DatabaseManager = Depends(get_db)):
    if not copilot.delete_thread(db, thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"success": True}


@router.get("/retrieve")
async def retrieve(question: str, project_id: Optional[str] = None,
                   db: DatabaseManager = Depends(get_db)):
    """Exposed on its own so the UI can show what an answer *would* cite."""
    return {"hits": copilot.retrieve(db, question, project_id)}


# --- Next best action (D22) --------------------------------------------------
@router.get("/next-action/{project_id}")
async def next_action(project_id: str, phrase: bool = True,
                      db: DatabaseManager = Depends(get_db)):
    return await nba_service.next_best_action(db, project_id, phrase)


@router.get("/signals/{project_id}")
async def signals(project_id: str, db: DatabaseManager = Depends(get_db)):
    """The raw deterministic signals, with no model involved."""
    return {"suggestions": nba_service.compute(db, project_id)}


# --- Prioritization (D23) ----------------------------------------------------
@router.post("/prioritize/{project_id}/{feature_id}")
async def suggest_scores(project_id: str, feature_id: str, model: str = "",
                         db: DatabaseManager = Depends(get_db)):
    try:
        return await prioritize_ai.suggest_scores(db, project_id, feature_id, model)
    except prioritize_ai.PrioritizeError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/prioritize/{project_id}")
async def list_suggestions(project_id: str, status: str = "pending",
                           db: DatabaseManager = Depends(get_db)):
    return {"suggestions": prioritize_ai.list_suggestions(db, project_id, status)}


@router.post("/prioritize/accept/{suggestion_id}")
async def accept_suggestion(suggestion_id: str, req: AcceptScores,
                            db: DatabaseManager = Depends(get_db)):
    try:
        return prioritize_ai.accept(db, suggestion_id, req.impact, req.effort, req.risk)
    except prioritize_ai.PrioritizeError as e:
        code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/prioritize/reject/{suggestion_id}")
async def reject_suggestion(suggestion_id: str, db: DatabaseManager = Depends(get_db)):
    if not prioritize_ai.reject(db, suggestion_id):
        raise HTTPException(status_code=404, detail="Suggestion not found or already decided")
    return {"success": True}


# --- Prompt library (D27) ----------------------------------------------------
@router.get("/prompts")
async def list_prompts(project_id: Optional[str] = None,
                       db: DatabaseManager = Depends(get_db)):
    return {"prompts": prompt_library.list_prompts(db, project_id)}


@router.post("/prompts")
async def create_prompt(req: PromptCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return prompt_library.create_prompt(db, req.project_id, req.name, req.body,
                                            req.task_type, req.description)
    except prompt_library.PromptError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/prompts/{prompt_id}/fork")
async def fork_prompt(prompt_id: str, project_id: str,
                      db: DatabaseManager = Depends(get_db)):
    try:
        return prompt_library.fork_prompt(db, prompt_id, project_id)
    except prompt_library.PromptError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, req: PromptUpdate,
                        db: DatabaseManager = Depends(get_db)):
    try:
        return prompt_library.update_prompt(db, prompt_id, req.body, req.name,
                                            req.description)
    except prompt_library.PromptError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        if not prompt_library.delete_prompt(db, prompt_id):
            raise HTTPException(status_code=404, detail="Prompt not found")
    except prompt_library.PromptError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.post("/prompts/{prompt_id}/render")
async def render_prompt(prompt_id: str, req: PromptRender,
                        db: DatabaseManager = Depends(get_db)):
    try:
        return prompt_library.render(db, prompt_id, req.values)
    except prompt_library.PromptError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.get("/prompts/{prompt_id}/diff")
async def diff_prompt(prompt_id: str, db: DatabaseManager = Depends(get_db)):
    try:
        return prompt_library.diff_against_origin(db, prompt_id)
    except prompt_library.PromptError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Model routing (D28) -----------------------------------------------------
@router.get("/routing")
async def get_routing():
    return model_routing.routing_table()


@router.post("/routing")
async def set_routing(req: RouteSet):
    try:
        return {"routes": model_routing.set_route(req.task_type, req.model)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Usage dashboard (D30) ---------------------------------------------------
@router.get("/usage")
async def usage(project_id: Optional[str] = None, days: int = 30,
                db: DatabaseManager = Depends(get_db)):
    from src.settings import get_settings

    settings = get_settings()
    return model_telemetry.usage(
        db, project_id, days,
        watts=getattr(settings, "power_watts", 60.0),
        rate_per_kwh=getattr(settings, "electricity_rate_per_kwh", 0.15),
    )


@router.get("/usage/recent")
async def recent_calls(project_id: Optional[str] = None, limit: int = 50,
                       db: DatabaseManager = Depends(get_db)):
    return {"calls": model_telemetry.recent(db, limit, project_id)}
