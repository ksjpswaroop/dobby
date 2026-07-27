"""
Model-call telemetry and the usage dashboard (100-Day Roadmap, Day 30).

Local inference has no invoice, so "cost" here is derived from wall-clock
time against a configurable machine power draw and electricity rate. That is
an estimate and is labelled as one everywhere it surfaces — the useful signal
is *relative*: which task type and which model are eating your afternoon.

Token counts are likewise estimated (~4 chars/token) because local runtimes
do not report usage. `tokens_estimated` flags every such row, so a provider
that reports real counts can be told apart from one that does not.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.db.copilot_models import TASK_TYPES, ModelCall
from src.db.schema import DatabaseManager

CHARS_PER_TOKEN = 4

# Defaults for the local-cost estimate. Deliberately conservative and
# overridable in Settings — a laptop and a workstation differ by an order of
# magnitude, and a wrong-by-10x number presented confidently is worse than none.
DEFAULT_WATTS = 60.0
DEFAULT_RATE_PER_KWH = 0.15


def estimate_tokens(text: str) -> int:
    return max(0, len(text or "") // CHARS_PER_TOKEN)


def record(db: DatabaseManager, task_type: str, model: str, *,
           project_id: Optional[str] = None, provider: str = "",
           prompt: str = "", output: str = "", latency_ms: int = 0,
           ok: bool = True, error: str = "") -> str:
    """Log one model call. Never raises — telemetry must not break the caller."""
    try:
        if task_type not in TASK_TYPES:
            task_type = "other"
        with db.get_session() as s:
            call = ModelCall(
                id=str(uuid.uuid4()), project_id=project_id, task_type=task_type,
                model=model or "unknown", provider=provider,
                prompt_chars=len(prompt or ""), output_chars=len(output or ""),
                prompt_tokens=estimate_tokens(prompt), output_tokens=estimate_tokens(output),
                tokens_estimated=1, latency_ms=int(latency_ms),
                ok=1 if ok else 0, error=(error or "")[:1000],
            )
            s.add(call)
            s.commit()
            return call.id
    except Exception:
        return ""


def _cost(seconds: float, watts: float, rate: float) -> float:
    return (watts * seconds / 3600.0 / 1000.0) * rate


def usage(db: DatabaseManager, project_id: Optional[str] = None, days: int = 30,
          watts: float = DEFAULT_WATTS,
          rate_per_kwh: float = DEFAULT_RATE_PER_KWH) -> Dict[str, Any]:
    """Aggregate usage for the dashboard: totals, per-model, per-task, daily."""
    since = datetime.utcnow() - timedelta(days=days)
    with db.get_session() as s:
        q = s.query(ModelCall).filter(ModelCall.created_at >= since)
        if project_id:
            q = q.filter(ModelCall.project_id == project_id)
        calls = q.all()

    total_ms = sum(c.latency_ms or 0 for c in calls)
    total_tokens = sum((c.prompt_tokens or 0) + (c.output_tokens or 0) for c in calls)

    by_model: Dict[str, Dict[str, Any]] = {}
    by_task: Dict[str, Dict[str, Any]] = {}
    by_day: Dict[str, Dict[str, Any]] = {}

    for c in calls:
        tokens = (c.prompt_tokens or 0) + (c.output_tokens or 0)

        m = by_model.setdefault(c.model, {"model": c.model, "calls": 0, "tokens": 0,
                                          "total_ms": 0, "failures": 0})
        m["calls"] += 1
        m["tokens"] += tokens
        m["total_ms"] += c.latency_ms or 0
        if not c.ok:
            m["failures"] += 1

        t = by_task.setdefault(c.task_type, {"task_type": c.task_type, "calls": 0,
                                             "tokens": 0, "total_ms": 0})
        t["calls"] += 1
        t["tokens"] += tokens
        t["total_ms"] += c.latency_ms or 0

        day = (c.created_at or datetime.utcnow()).date().isoformat()
        d = by_day.setdefault(day, {"date": day, "calls": 0, "tokens": 0, "total_ms": 0})
        d["calls"] += 1
        d["tokens"] += tokens
        d["total_ms"] += c.latency_ms or 0

    for m in by_model.values():
        m["avg_ms"] = round(m["total_ms"] / m["calls"]) if m["calls"] else 0
    for t in by_task.values():
        t["avg_ms"] = round(t["total_ms"] / t["calls"]) if t["calls"] else 0

    return {
        "days": days,
        "total_calls": len(calls),
        "total_tokens": total_tokens,
        "total_ms": total_ms,
        "failures": sum(1 for c in calls if not c.ok),
        "avg_ms": round(total_ms / len(calls)) if calls else 0,
        "estimated_cost": round(_cost(total_ms / 1000.0, watts, rate_per_kwh), 4),
        "cost_basis": {
            "watts": watts, "rate_per_kwh": rate_per_kwh,
            "note": "Local inference has no invoice — this is time x power x rate, an estimate.",
        },
        "tokens_are_estimated": True,
        "by_model": sorted(by_model.values(), key=lambda x: -x["calls"]),
        "by_task": sorted(by_task.values(), key=lambda x: -x["calls"]),
        "by_day": sorted(by_day.values(), key=lambda x: x["date"]),
    }


def recent(db: DatabaseManager, limit: int = 50,
           project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        q = s.query(ModelCall)
        if project_id:
            q = q.filter(ModelCall.project_id == project_id)
        rows = q.order_by(ModelCall.created_at.desc()).limit(min(limit, 200)).all()
        return [{
            "id": c.id, "task_type": c.task_type, "model": c.model,
            "latency_ms": c.latency_ms,
            "tokens": (c.prompt_tokens or 0) + (c.output_tokens or 0),
            "ok": bool(c.ok), "error": c.error,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        } for c in rows]
