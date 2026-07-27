"""
Runs API — Logs & Traces.

- GET  /runs                  list recent runs (optionally by project)
- GET  /runs/{run_id}         one run + its full event timeline
- GET  /runs/stream           Server-Sent Events: live run/step events
- DELETE /runs                clear run history

The stream is what turns a multi-minute generation from a blank spinner into
visible, step-by-step progress.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.db.run_models import Run, RunEvent
from src.db.schema import DatabaseManager
from src.observability.tracer import subscribe, unsubscribe
from src.services.run_todo import derive_todo

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["Runs"])


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


def _run_dict(r: Run) -> Dict[str, Any]:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "kind": r.kind,
        "label": r.label,
        "status": r.status,
        "model": r.model,
        "node_id": r.node_id,
        "error": r.error,
        "total_steps": r.total_steps or 0,
        "completed_steps": r.completed_steps or 0,
        "score": r.score,
        "duration_ms": r.duration_ms,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.get("/runs")
async def list_runs(
    project_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: DatabaseManager = Depends(get_db),
) -> Dict[str, Any]:
    with db.get_session() as s:
        q = s.query(Run)
        if project_id:
            q = q.filter(Run.project_id == project_id)
        runs = q.order_by(Run.started_at.desc()).limit(limit).all()
    return {"count": len(runs), "runs": [_run_dict(r) for r in runs]}


@router.get("/runs/stream")
async def stream_runs() -> StreamingResponse:
    """Live event stream (SSE). Emits every run/step event as it happens."""
    q = subscribe()

    async def gen():
        try:
            # Prime the connection so the client's onopen fires immediately.
            yield "event: ping\ndata: {}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # stops proxies/browsers idling out
        finally:
            unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _event_dict(e: RunEvent) -> Dict[str, Any]:
    return {
        "seq": e.seq,
        "level": e.level,
        "event": e.event,
        "message": e.message,
        "step": e.step,
        "duration_ms": e.duration_ms,
        "tokens": e.tokens,
        "score": e.score,
        "ts": e.ts.isoformat() if e.ts else None,
    }


def _load_run_and_events(db: DatabaseManager, run_id: str) -> tuple[Run, List[Dict[str, Any]]]:
    with db.get_session() as s:
        run = s.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        events = (
            s.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.seq).all()
        )
        return run, [_event_dict(e) for e in events]


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
    run, events = _load_run_and_events(db, run_id)
    return {"run": _run_dict(run), "events": events}


@router.get("/runs/{run_id}/todo")
async def get_run_todo(run_id: str, db: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
    """A checklist view of the run, derived from its event stream.

    Distinct from the step-by-step log above: this collapses the same events
    into done/in-progress/failed/pending tasks rather than a scrolling trace.
    """
    run, events = _load_run_and_events(db, run_id)
    run_dict = _run_dict(run)
    return {"run": run_dict, "todo": derive_todo(run_dict, events)}


@router.delete("/runs")
async def clear_runs(
    project_id: Optional[str] = None, db: DatabaseManager = Depends(get_db)
) -> Dict[str, Any]:
    with db.get_session() as s:
        q = s.query(Run)
        if project_id:
            q = q.filter(Run.project_id == project_id)
        ids = [r.id for r in q.all()]
        if ids:
            s.query(RunEvent).filter(RunEvent.run_id.in_(ids)).delete(synchronize_session=False)
            s.query(Run).filter(Run.id.in_(ids)).delete(synchronize_session=False)
            s.commit()
    return {"deleted": len(ids)}
