"""Webhooks, API keys, and recipes (Phase 6: D58, D59, D60)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.db.integration_models import (
    API_SCOPES, RECIPE_ACTIONS, RECIPE_TRIGGERS, WEBHOOK_EVENTS,
)
from src.db.schema import DatabaseManager
from src.services import integration_service as svc

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class WebhookCreate(BaseModel):
    project_id: str
    url: str
    events: List[str]
    description: str = ""


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: List[str]
    project_id: Optional[str] = None


class RecipeCreate(BaseModel):
    project_id: str
    name: str = Field(..., min_length=1, max_length=120)
    trigger: str
    action: str
    action_params: Dict[str, Any] = Field(default_factory=dict)
    condition: Dict[str, Any] = Field(default_factory=dict)


class FireEvent(BaseModel):
    project_id: str
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.get("/meta")
async def meta():
    return {"webhook_events": list(WEBHOOK_EVENTS), "scopes": list(API_SCOPES),
            "recipe_triggers": list(RECIPE_TRIGGERS),
            "recipe_actions": list(RECIPE_ACTIONS)}


# --- Webhooks ---------------------------------------------------------------
@router.get("/webhooks/{project_id}")
async def list_webhooks(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"webhooks": svc.list_webhooks(db, project_id)}


@router.post("/webhooks")
async def create_webhook(req: WebhookCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.create_webhook(db, req.project_id, req.url, req.events,
                                        req.description)
    except svc.IntegrationError as e:
        code = 403 if "not approved" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_webhook(db, webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"success": True}


@router.get("/webhooks/{webhook_id}/deliveries")
async def deliveries(webhook_id: str, db: DatabaseManager = Depends(get_db)):
    return {"deliveries": svc.deliveries(db, webhook_id)}


@router.post("/webhooks/fire")
async def fire(req: FireEvent, db: DatabaseManager = Depends(get_db)):
    return await svc.fire(db, req.project_id, req.event, req.payload)


# --- API keys ---------------------------------------------------------------
@router.get("/keys")
async def list_keys(db: DatabaseManager = Depends(get_db)):
    return {"keys": svc.list_api_keys(db)}


@router.post("/keys")
async def create_key(req: ApiKeyCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_api_key(db, req.name, req.scopes, req.project_id)
    except svc.IntegrationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.revoke_api_key(db, key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"success": True}


# --- Recipes ----------------------------------------------------------------
@router.get("/recipes/{project_id}")
async def list_recipes(project_id: str, db: DatabaseManager = Depends(get_db)):
    return {"recipes": svc.list_recipes(db, project_id)}


@router.post("/recipes")
async def create_recipe(req: RecipeCreate, db: DatabaseManager = Depends(get_db)):
    try:
        return svc.create_recipe(db, req.project_id, req.name, req.trigger,
                                 req.action, req.action_params, req.condition)
    except svc.IntegrationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(recipe_id: str, db: DatabaseManager = Depends(get_db)):
    if not svc.delete_recipe(db, recipe_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return {"success": True}


@router.post("/recipes/run")
async def run_recipes(req: FireEvent, db: DatabaseManager = Depends(get_db)):
    return await svc.run_recipes(db, req.project_id, req.event, req.payload)
