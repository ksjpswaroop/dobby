"""
Automation service — CRUD, firing, and the background scheduler loop.

Behaviours ported from OpenWorker's scheduler (roadmap tab `OW · Features`):

* **Always-on loop.** A task ticks every 30s inside the API process. No external
  cron, no second daemon — the app is the scheduler, which is the only design
  that works for a local desktop app that is sometimes closed.
* **Catch-up on startup.** Anything whose `next_run` passed while the app was
  shut runs once on boot, rather than being silently lost. Once — not once per
  missed interval — because waking to forty queued digests is worse than
  missing thirty-nine.
* **Skip-on-overlap.** A firing still in flight blocks the next one, recorded
  as `skipped` rather than dropped, so the history shows what happened.
* **Max-runs cap** and **enable/disable**, so a misconfigured schedule cannot
  run forever.
* **Unread tracking**, so a finished run can ask for attention.

Every firing writes to the audit trail and, where it starts real work, a `Run`
row — so a scheduled job is inspectable exactly like an interactive one.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

from src.db.automation_models import (
    ACTION_KINDS, TRIGGER_KINDS, Automation, AutomationRun,
)
from src.db.schema import DatabaseManager, Project
from src.scheduler import cron

logger = structlog.get_logger()

TICK_SECONDS = 30
# A missed run older than this is not worth catching up — the moment has passed.
CATCHUP_GRACE = timedelta(hours=24)


class AutomationError(Exception):
    """Invalid automation definition. Message is user-facing."""


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite columns are naive; normalise everything to naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _now() -> datetime:
    return datetime.utcnow()


def compute_next(auto: Automation, after: Optional[datetime] = None) -> Optional[datetime]:
    """When this automation should next fire, as naive UTC."""
    if auto.trigger == "once":
        run_at = _naive_utc(auto.run_at)
        # A one-shot that has already run has no next time.
        return None if (auto.run_count or 0) > 0 else run_at
    base = (after or _now()).replace(tzinfo=timezone.utc)
    nxt = cron.next_fire(auto.cron, base, auto.timezone)
    return _naive_utc(nxt)


def _to_dict(a: Automation) -> Dict[str, Any]:
    return {
        "id": a.id, "project_id": a.project_id, "name": a.name,
        "description": a.description, "action": a.action,
        "action_config": a.action_config or {}, "trigger": a.trigger,
        "cron": a.cron, "timezone": a.timezone,
        "run_at": a.run_at.isoformat() if a.run_at else None,
        "enabled": bool(a.enabled), "max_runs": a.max_runs or 0,
        "run_count": a.run_count or 0, "is_running": bool(a.is_running),
        "next_run": a.next_run.isoformat() if a.next_run else None,
        "last_run": a.last_run.isoformat() if a.last_run else None,
        "last_status": a.last_status, "last_error": a.last_error,
        "unread_count": a.unread_count or 0,
        "schedule_text": (cron.describe(a.cron, a.timezone) if a.trigger == "cron"
                          else f"Once at {a.run_at:%Y-%m-%d %H:%M} UTC" if a.run_at
                          else "Once"),
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create(db: DatabaseManager, project_id: str, name: str, action: str,
           trigger: str = "cron", cron_expr: str = "", run_at: Optional[str] = None,
           tz: str = "UTC", action_config: Optional[Dict[str, Any]] = None,
           description: str = "", max_runs: int = 0) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise AutomationError("Give the automation a name.")
    if action not in ACTION_KINDS:
        raise AutomationError(f"Unknown action. Choose one of: {', '.join(ACTION_KINDS)}")
    if trigger not in TRIGGER_KINDS:
        raise AutomationError(f"Trigger must be one of: {', '.join(TRIGGER_KINDS)}")

    parsed_run_at: Optional[datetime] = None
    if trigger == "cron":
        try:
            cron.parse(cron_expr)
        except cron.CronError as e:
            raise AutomationError(str(e))
    else:
        if not run_at:
            raise AutomationError("A one-off automation needs a date and time.")
        try:
            parsed_run_at = _naive_utc(datetime.fromisoformat(run_at.replace("Z", "+00:00")))
        except ValueError:
            raise AutomationError("Could not read that date and time.")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise AutomationError("Project not found.")
        auto = Automation(
            id=str(uuid.uuid4()), project_id=project_id, name=name[:200],
            description=(description or "")[:2000], action=action,
            action_config=action_config or {}, trigger=trigger,
            cron=cron_expr or "", run_at=parsed_run_at, timezone=tz or "UTC",
            enabled=True, max_runs=max(0, int(max_runs or 0)),
        )
        auto.next_run = compute_next(auto)
        s.add(auto)
        s.commit()
        result = _to_dict(auto)

    _audit(db, project_id, auto_id=result["id"], action="created", detail=name)
    logger.info("automation_created", id=result["id"], name=name)
    return result


def list_for_project(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(Automation)
                .filter(Automation.project_id == project_id)
                .order_by(Automation.created_at.desc()).all())
        return [_to_dict(a) for a in rows]


def get(db: DatabaseManager, automation_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        a = s.get(Automation, automation_id)
        return _to_dict(a) if a else None


def set_enabled(db: DatabaseManager, automation_id: str,
                enabled: bool) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        a = s.get(Automation, automation_id)
        if not a:
            return None
        a.enabled = enabled
        # Re-arm from now when switching back on, so a long-disabled automation
        # does not immediately fire for every interval it slept through.
        a.next_run = compute_next(a) if enabled else None
        a.updated_at = _now()
        s.commit()
        out = _to_dict(a)
    _audit(db, out["project_id"], automation_id, "enabled" if enabled else "disabled",
           out["name"])
    return out


def delete(db: DatabaseManager, automation_id: str) -> bool:
    with db.get_session() as s:
        a = s.get(Automation, automation_id)
        if not a:
            return False
        project_id, name = a.project_id, a.name
        s.query(AutomationRun).filter(
            AutomationRun.automation_id == automation_id
        ).delete(synchronize_session=False)
        s.delete(a)
        s.commit()
    _audit(db, project_id, automation_id, "deleted", name)
    return True


def list_runs(db: DatabaseManager, automation_id: str,
              limit: int = 50) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(AutomationRun)
                .filter(AutomationRun.automation_id == automation_id)
                .order_by(AutomationRun.started_at.desc()).limit(limit).all())
        return [{
            "id": r.id, "run_id": r.run_id, "status": r.status,
            "trigger_source": r.trigger_source, "summary": r.summary,
            "error": r.error, "read": bool(r.read), "duration_ms": r.duration_ms,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        } for r in rows]


def mark_read(db: DatabaseManager, automation_id: str) -> Dict[str, Any]:
    """Clear the unread badge once the user has looked at the runs."""
    with db.get_session() as s:
        s.query(AutomationRun).filter(
            AutomationRun.automation_id == automation_id,
            AutomationRun.read.is_(False),
        ).update({"read": True}, synchronize_session=False)
        a = s.get(Automation, automation_id)
        if a:
            a.unread_count = 0
        s.commit()
    return {"success": True}


def unread_total(db: DatabaseManager, project_id: str) -> int:
    with db.get_session() as s:
        rows = (s.query(Automation.unread_count)
                .filter(Automation.project_id == project_id).all())
        return sum(int(r[0] or 0) for r in rows)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def _audit(db: DatabaseManager, project_id: str, auto_id: str,
           action: str, detail: str = "") -> None:
    """Record to the local audit log.

    Uses `AuditTrailManager`, which existed in the codebase but had no callers
    at all — the audit endpoint queried the table directly. Scheduled work
    running while nobody is watching is exactly what an audit trail is for, so
    this is where it earns its place.
    """
    try:
        from src.audit.trail import get_audit_trail_manager

        get_audit_trail_manager(db).log(
            project_id=project_id,
            action=f"automation.{action}",
            user_id="scheduler",
            metadata={"automation_id": auto_id, "detail": detail[:400]},
        )
    except Exception as e:  # auditing must never break the operation
        logger.warning("audit_write_failed", error=str(e), action=action)


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------
async def fire(db: DatabaseManager, automation_id: str,
               source: str = "schedule") -> Dict[str, Any]:
    """Run one automation now.

    Returns a result dict rather than raising, because the scheduler loop must
    survive a failing automation — one broken task cannot stop every other.
    """
    with db.get_session() as s:
        a = s.get(Automation, automation_id)
        if not a:
            return {"success": False, "error": "Automation not found"}
        if a.is_running:
            # Skip-on-overlap: recorded, not silently dropped.
            s.add(AutomationRun(
                id=str(uuid.uuid4()), automation_id=automation_id,
                status="skipped", trigger_source=source,
                summary="Previous run was still in progress.",
                started_at=_now(), finished_at=_now(),
            ))
            a.last_status = "skipped"
            a.next_run = compute_next(a)
            s.commit()
            return {"success": False, "skipped": True,
                    "error": "Still running from the last trigger."}
        if a.max_runs and (a.run_count or 0) >= a.max_runs:
            a.enabled = False
            a.next_run = None
            a.last_status = "capped"
            s.commit()
            return {"success": False, "error": "Run limit reached; automation disabled."}

        a.is_running = True
        s.commit()
        project_id, action, config, name = a.project_id, a.action, dict(a.action_config or {}), a.name

    run_row = AutomationRun(
        id=str(uuid.uuid4()), automation_id=automation_id, status="running",
        trigger_source=source, started_at=_now(),
    )
    with db.get_session() as s:
        s.add(run_row)
        s.commit()
        run_row_id = run_row.id

    started = _now()
    status, summary, error, run_id = "ok", "", None, None
    try:
        summary, run_id = await _execute(db, project_id, action, config, name)
    except Exception as e:
        status, error = "failed", str(e)[:500]
        logger.exception("automation_failed", id=automation_id)

    finished = _now()
    duration = int((finished - started).total_seconds() * 1000)

    with db.get_session() as s:
        r = s.get(AutomationRun, run_row_id)
        if r:
            r.status, r.summary, r.error = status, summary[:2000], error
            r.run_id, r.duration_ms, r.finished_at = run_id, duration, finished
        a = s.get(Automation, automation_id)
        if a:
            a.is_running = False
            a.run_count = (a.run_count or 0) + 1
            a.last_run, a.last_status, a.last_error = finished, status, error
            a.unread_count = (a.unread_count or 0) + 1
            if a.max_runs and a.run_count >= a.max_runs:
                a.enabled, a.next_run = False, None
            else:
                a.next_run = compute_next(a, finished)
        s.commit()

    _audit(db, project_id, automation_id, f"ran:{status}", summary[:200])
    logger.info("automation_fired", id=automation_id, status=status, ms=duration)
    return {"success": status == "ok", "status": status, "summary": summary,
            "error": error, "run_id": run_id}


async def _execute(db: DatabaseManager, project_id: str, action: str,
                   config: Dict[str, Any], name: str) -> tuple[str, Optional[str]]:
    """Do the actual work. Returns (summary, run_id)."""
    if action == "research":
        from src.services import research_service as rs

        topic = (config.get("topic") or name).strip()
        brief = rs.create_brief(db, project_id, topic, config.get("context", ""))
        result = await rs.run_brief(db, brief["id"])
        n = sum(len(t["learnings"]) for t in result["tracks"])
        conflicts = len((result.get("audit") or {}).get("conflicts", []))
        note = f", {conflicts} contradiction(s)" if conflicts else ""
        return (f"Researched “{topic}” — {n} findings across "
                f"{len(result['tracks'])} tracks{note}."), result.get("run_id")

    if action == "digest":
        return _digest(db, project_id), None

    if action == "verify":
        from src.db.schema import Node

        with db.get_session() as s:
            pending = (s.query(Node)
                       .filter(Node.project_id == project_id,
                               Node.status == "pending_review").count())
        return f"{pending} document(s) awaiting review.", None

    if action == "generate":
        from src.pipeline.yolo import YOLOPipeline
        from src.db.schema import FeatureBacklog

        with db.get_session() as s:
            feature = (s.query(FeatureBacklog)
                       .filter(FeatureBacklog.project_id == project_id,
                               FeatureBacklog.status == "backlog")
                       .order_by(FeatureBacklog.pareto_score.desc()).first())
            if not feature:
                return "Nothing in the backlog to generate.", None
            title, fid = feature.title, feature.id

        pipeline = YOLOPipeline(db)
        result = await pipeline.generate(project_id, title, feature_id=fid)
        return f"Generated documents for “{title}”.", (result or {}).get("run_id")

    raise AutomationError(f"Unknown action: {action}")


def _digest(db: DatabaseManager, project_id: str) -> str:
    """A short summary of what changed — the 'morning brief' pattern."""
    from src.db.schema import FeatureBacklog, Node
    from src.db.run_models import Run

    since = _now() - timedelta(days=1)
    with db.get_session() as s:
        docs = (s.query(Node)
                .filter(Node.project_id == project_id, Node.created_at >= since).count())
        runs = (s.query(Run)
                .filter(Run.project_id == project_id, Run.started_at >= since).count())
        backlog = (s.query(FeatureBacklog)
                   .filter(FeatureBacklog.project_id == project_id,
                           FeatureBacklog.status == "backlog").count())
    return (f"Last 24h: {docs} document(s) created, {runs} run(s). "
            f"{backlog} feature(s) waiting in the backlog.")


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def due_automations(db: DatabaseManager, now: Optional[datetime] = None) -> List[str]:
    now = now or _now()
    with db.get_session() as s:
        rows = (s.query(Automation.id)
                .filter(Automation.enabled.is_(True),
                        Automation.is_running.is_(False),
                        Automation.next_run.isnot(None),
                        Automation.next_run <= now).all())
        return [r[0] for r in rows]


def catch_up_targets(db: DatabaseManager) -> List[str]:
    """Automations whose time passed while the app was closed.

    Anything older than the grace window is re-armed instead of run: waking to
    a day-old digest is useful, waking to last month's is not.
    """
    now = _now()
    stale_cutoff = now - CATCHUP_GRACE
    due: List[str] = []
    with db.get_session() as s:
        rows = (s.query(Automation)
                .filter(Automation.enabled.is_(True),
                        Automation.next_run.isnot(None),
                        Automation.next_run <= now).all())
        for a in rows:
            if a.next_run and a.next_run < stale_cutoff:
                a.next_run = compute_next(a, now)   # too old — just re-arm
            else:
                due.append(a.id)
            # A crash mid-run would leave this set forever; startup is the
            # right moment to clear it.
            a.is_running = False
        s.commit()
    return due


class SchedulerLoop:
    """The always-on ticker. One per process, started in the app lifespan."""

    def __init__(self, db: DatabaseManager, interval: int = TICK_SECONDS):
        self.db = db
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.ticks = 0

    async def _run(self) -> None:
        try:
            for automation_id in catch_up_targets(self.db):
                logger.info("automation_catchup", id=automation_id)
                await fire(self.db, automation_id, source="catchup")
        except Exception:
            logger.exception("automation_catchup_failed")

        while not self._stop.is_set():
            try:
                self.ticks += 1
                for automation_id in due_automations(self.db):
                    await fire(self.db, automation_id, source="schedule")
            except Exception:
                # A bad tick must never kill the loop.
                logger.exception("scheduler_tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run())
            logger.info("scheduler_started", interval=self.interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        logger.info("scheduler_stopped", ticks=self.ticks)
