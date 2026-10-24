"""Model provider API — what is available, and what it can do."""

from typing import List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.llm import providers as P

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/providers", tags=["Providers"])


class RouteRequest(BaseModel):
    required: List[str] = []
    prefer: str = ""


@router.get("")
async def list_providers():
    """Configured providers and whether each is reachable."""
    import asyncio

    configured = P.configured_providers()
    healths = await asyncio.gather(*(p.health() for p in configured),
                                   return_exceptions=True)
    return {
        "providers": [
            {
                "name": p.name,
                "is_local": p.is_local,
                "health": h if not isinstance(h, Exception) else
                          {"reachable": False, "error": str(h)},
            }
            for p, h in zip(configured, healths)
        ],
        "capabilities": [c.value for c in P.Capability],
    }


@router.get("/models")
async def list_models():
    """Every reachable model across every configured provider."""
    models = await P.available_models()
    return {"models": [m.to_dict() for m in models]}


@router.post("/route")
async def route(req: RouteRequest):
    """Which model would be chosen for a set of required capabilities."""
    try:
        required = [P.Capability(c) for c in req.required]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Unknown capability: {e}")
    chosen = await P.route(required, prefer=req.prefer)
    if not chosen:
        raise HTTPException(
            status_code=404,
            detail="No configured model satisfies those requirements.",
        )
    return chosen.to_dict()
