"""Scale, ecosystem & ritual API (Phase 10: D94-D100)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.db.schema import DatabaseManager
from src.services import platform_service as svc

router = APIRouter(prefix="/api/v1/platform", tags=["Platform"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class LanguageSet(BaseModel):
    code: str


class HelpQuestion(BaseModel):
    question: str
    model: str = ""


@router.get("/meta")
async def meta():
    return {"languages": svc.LANGUAGES, "goals": [
        {"slug": g["slug"], "name": g["name"], "blurb": g["blurb"]}
        for g in svc.GUIDED_GOALS]}


@router.get("/language")
async def get_language():
    return svc.get_language()


@router.post("/language")
async def set_language(req: LanguageSet):
    try:
        return svc.set_language(req.code)
    except svc.PlatformError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/models")
async def model_catalog():
    return await svc.model_catalog()


@router.get("/help")
async def search_help(q: str, limit: int = 5):
    return svc.search_help(q, limit)


@router.post("/help")
async def answer_help(req: HelpQuestion, db: DatabaseManager = Depends(get_db)):
    return await svc.answer_help(db, req.question, req.model)


@router.get("/goals/{project_id}")
async def goals(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"goals": svc.goal_progress(db, project_id)}


@router.get("/recommendations/{project_id}")
async def recommendations(project_id: str, db: DatabaseManager = Depends(get_db)):
    return await svc.recommendations(db, project_id)


@router.get("/admin")
async def admin(db: DatabaseManager = Depends(get_db)):
    return svc.admin_console(db)


@router.get("/start-your-day/{project_id}")
async def start_your_day(project_id: str, db: DatabaseManager = Depends(get_db)):
    return await svc.start_your_day(db, project_id)
