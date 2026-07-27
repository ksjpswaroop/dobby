"""
Per-task model routing (100-Day Roadmap, Day 28).

The point is pairing: a small fast model for chat, a larger one for document
drafts. Routes live in settings as a `{task_type: model}` map; an unset task
falls through to the global default model, so routing is purely additive and
an empty map behaves exactly like the app did before.

`call()` is the single entry point every Phase 3 feature uses, because it is
the one place that both resolves the route *and* writes telemetry. Bypassing
it would silently create model calls the usage dashboard cannot see.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import structlog

from src.db.copilot_models import TASK_TYPES
from src.db.schema import DatabaseManager
from src.services import model_telemetry

logger = structlog.get_logger()


def get_routes() -> Dict[str, str]:
    from src.settings import get_settings

    routes = getattr(get_settings(), "model_routes", None) or {}
    return {k: v for k, v in routes.items() if k in TASK_TYPES and v}


def set_route(task_type: str, model: str) -> Dict[str, str]:
    from src.settings import get_settings, get_settings_store

    if task_type not in TASK_TYPES:
        raise ValueError(f"Unknown task type. One of: {', '.join(TASK_TYPES)}")

    routes = dict(getattr(get_settings(), "model_routes", None) or {})
    if model:
        routes[task_type] = model
    else:
        routes.pop(task_type, None)  # empty model = fall back to the default
    get_settings_store().update(model_routes=routes)
    return routes


def resolve(task_type: str, explicit: str = "") -> str:
    """An explicit per-call model always wins over the configured route."""
    if explicit:
        return explicit
    return get_routes().get(task_type, "")


async def call(db: Optional[DatabaseManager], task_type: str, prompt: str, *,
               model: str = "", system: str = "", max_tokens: int = 1500,
               temperature: float = 0.4, project_id: Optional[str] = None,
               json_mode: bool = False) -> str:
    """Route, invoke, and log one model call.

    Failures are logged to telemetry *before* being re-raised, so a model that
    keeps timing out shows up in the dashboard rather than vanishing.
    """
    from src.llm.providers import generate

    chosen = resolve(task_type, model)
    started = time.monotonic()
    try:
        out = await generate(prompt, model=chosen, system=system,
                             max_tokens=max_tokens, temperature=temperature,
                             json_mode=json_mode)
    except Exception as e:
        if db is not None:
            model_telemetry.record(
                db, task_type, chosen or "default", project_id=project_id,
                prompt=prompt, latency_ms=int((time.monotonic() - started) * 1000),
                ok=False, error=str(e),
            )
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    if db is not None:
        model_telemetry.record(
            db, task_type, chosen or "default", project_id=project_id,
            prompt=prompt, output=out, latency_ms=latency_ms,
        )
    return out


def routing_table() -> Dict[str, Any]:
    routes = get_routes()
    return {
        "task_types": list(TASK_TYPES),
        "routes": routes,
        "unrouted": [t for t in TASK_TYPES if t not in routes],
    }
