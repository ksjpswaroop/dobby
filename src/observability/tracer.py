"""
Tracer — records runs and their events, and fans them out to live subscribers.

Two jobs:

1. **Persist** every run + event to SQLite so Logs & Traces can show history
   long after the run finished.
2. **Broadcast** each event to in-process subscribers so the UI can stream live
   progress (SSE) instead of staring at a spinner.

Tracing must never break generation: every write is best-effort and swallows
its own errors.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.run_models import Run, RunEvent
from src.db.schema import DatabaseManager

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Live fan-out: subscribers are asyncio queues, one per connected UI stream.
# ---------------------------------------------------------------------------
_subscribers: List["asyncio.Queue[Dict[str, Any]]"] = []


def subscribe() -> "asyncio.Queue[Dict[str, Any]]":
    q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=500)
    _subscribers.append(q)
    return q


def unsubscribe(q: "asyncio.Queue[Dict[str, Any]]") -> None:
    if q in _subscribers:
        _subscribers.remove(q)


def _publish(payload: Dict[str, Any]) -> None:
    """Push an event to every live subscriber, dropping on backpressure."""
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # a slow client must not stall generation


class Tracer:
    """Records one run. Use as a context manager or call finish() explicitly."""

    def __init__(
        self,
        db: DatabaseManager,
        kind: str,
        label: str,
        project_id: Optional[str] = None,
        model: Optional[str] = None,
        total_steps: int = 0,
    ):
        self.db = db
        self.run_id = str(uuid.uuid4())
        self.kind = kind
        self.label = label
        self.project_id = project_id
        self.model = model
        self.total_steps = total_steps
        self._seq = 0
        self._completed = 0
        self._started = datetime.utcnow()
        self._start_monotonic = asyncio.get_event_loop().time()
        self._create()

    # -- lifecycle ---------------------------------------------------------
    def _create(self) -> None:
        try:
            with self.db.get_session() as s:
                s.add(
                    Run(
                        id=self.run_id,
                        project_id=self.project_id,
                        kind=self.kind,
                        label=self.label,
                        status="running",
                        model=self.model,
                        total_steps=self.total_steps,
                        completed_steps=0,
                        started_at=self._started,
                    )
                )
                s.commit()
            _publish(
                {
                    "type": "run.start",
                    "run_id": self.run_id,
                    "kind": self.kind,
                    "label": self.label,
                    "total_steps": self.total_steps,
                    "ts": self._started.isoformat(),
                }
            )
        except Exception as e:  # tracing must never break generation
            logger.warning("tracer_create_failed", error=str(e))

    def event(
        self,
        event: str,
        message: str = "",
        *,
        level: str = "info",
        step: Optional[str] = None,
        duration_ms: Optional[int] = None,
        tokens: Optional[int] = None,
        score: Optional[float] = None,
        advance: bool = False,
        **metadata: Any,
    ) -> None:
        """Record one step. `advance=True` also bumps the progress counter."""
        self._seq += 1
        if advance:
            self._completed += 1
        ts = datetime.utcnow()
        try:
            with self.db.get_session() as s:
                s.add(
                    RunEvent(
                        id=str(uuid.uuid4()),
                        run_id=self.run_id,
                        seq=self._seq,
                        level=level,
                        event=event,
                        message=message,
                        step=step,
                        duration_ms=duration_ms,
                        tokens=tokens,
                        score=score,
                        extra_metadata=metadata or {},
                        ts=ts,
                    )
                )
                if advance:
                    run = s.get(Run, self.run_id)
                    if run:
                        run.completed_steps = self._completed
                s.commit()
        except Exception as e:
            logger.warning("tracer_event_failed", error=str(e))

        _publish(
            {
                "type": "run.event",
                "run_id": self.run_id,
                "seq": self._seq,
                "level": level,
                "event": event,
                "message": message,
                "step": step,
                "duration_ms": duration_ms,
                "tokens": tokens,
                "score": score,
                "completed_steps": self._completed,
                "total_steps": self.total_steps,
                "ts": ts.isoformat(),
            }
        )

    def finish(
        self,
        status: str = "ok",
        *,
        error: Optional[str] = None,
        score: Optional[float] = None,
        node_id: Optional[str] = None,
    ) -> None:
        finished = datetime.utcnow()
        duration_ms = int((finished - self._started).total_seconds() * 1000)
        try:
            with self.db.get_session() as s:
                run = s.get(Run, self.run_id)
                if run:
                    run.status = status
                    run.error = error
                    run.score = score
                    run.node_id = node_id
                    run.finished_at = finished
                    run.duration_ms = duration_ms
                    run.completed_steps = self._completed
                    s.commit()
        except Exception as e:
            logger.warning("tracer_finish_failed", error=str(e))

        _publish(
            {
                "type": "run.finish",
                "run_id": self.run_id,
                "status": status,
                "error": error,
                "score": score,
                "duration_ms": duration_ms,
                "ts": finished.isoformat(),
            }
        )

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> "Tracer":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.event("run.error", str(exc), level="error")
            self.finish("failed", error=str(exc))
        return False  # never swallow the original exception


def get_tracer(
    db: DatabaseManager,
    kind: str,
    label: str,
    project_id: Optional[str] = None,
    model: Optional[str] = None,
    total_steps: int = 0,
) -> Tracer:
    return Tracer(db, kind, label, project_id, model, total_steps)
