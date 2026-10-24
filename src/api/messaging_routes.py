"""Messaging API — connectors, subscriptions, webhooks, dead letters."""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.db.schema import DatabaseManager
from src.services import messaging_service as svc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/messaging", tags=["Messaging"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


class ConfigureRequest(BaseModel):
    credentials: Dict[str, str] = Field(default_factory=dict)


class SubscribeRequest(BaseModel):
    channel: str = Field(..., min_length=1)


class SendRequest(BaseModel):
    project_id: str = "default-project"
    channel: str
    text: str = Field(..., min_length=1)
    thread: Optional[str] = None


@router.get("/status")
async def status():
    return {"connectors": svc.status(), "health": await svc.health()}


@router.put("/{name}/configure")
async def configure(name: str, req: ConfigureRequest):
    try:
        return svc.configure(name, req.credentials)
    except svc.MessagingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{name}/subscriptions")
async def get_subscriptions(name: str):
    return {"subscriptions": svc.subscriptions(name)}


@router.post("/{name}/subscriptions")
async def add_subscription(name: str, req: SubscribeRequest):
    return {"subscriptions": svc.subscribe(name, req.channel)}


@router.delete("/{name}/subscriptions/{channel}")
async def remove_subscription(name: str, channel: str):
    return {"subscriptions": svc.unsubscribe(name, channel)}


@router.get("/{name}/recent")
async def recent(name: str):
    """The recent-channel buffer, so a restart keeps context."""
    return {"messages": svc.recent(name)}


@router.get("/dead-letters")
async def dead_letters():
    """Messages that could not be routed, and why."""
    return {"dead_letters": svc.dead_letters()}


@router.delete("/dead-letters")
async def clear_dead_letters():
    return {"cleared": svc.clear_dead_letters()}


@router.post("/{name}/send")
async def send(name: str, req: SendRequest, db: DatabaseManager = Depends(get_db)):
    try:
        return await svc.reply(db, req.project_id, name, req.channel,
                               req.text, req.thread)
    except svc.MessagingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{name}/webhook")
async def webhook(name: str, request: Request,
                  db: DatabaseManager = Depends(get_db)):
    """Inbound events. Signature-verified before the payload is looked at."""
    body = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body is not JSON")

    try:
        return await svc.handle_webhook(
            db, "default-project", name, body, dict(request.headers), payload
        )
    except svc.MessagingError as e:
        # 401 for a signature failure, 400 otherwise.
        code = 401 if "signature" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))
