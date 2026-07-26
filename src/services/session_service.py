"""
Durable sessions and the permission posture they carry.

The important function is `gate()`. It sits in front of `inbox.require()` and
applies the session's mode *before* anything reaches the Inbox:

* `readonly` refuses outright — before consulting grants, because a mode a
  standing grant could defeat would be a setting that lies.
* `unattended` lets low-risk actions through and records that it did, so the
  audit trail shows an automated decision rather than a human one. Medium and
  high risk still ask, which is what stops "unattended" quietly meaning
  "unsupervised".
* `ask` defers entirely to the Inbox.

Suspend/resume is checkpoint-based rather than process-based: state lives in the
row, so resuming after a crash, a restart, or a week is the same operation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager, Project
from src.db.session_models import (
    PERMISSION_MODES, SESSION_STATES, UNATTENDED_AUTO_RISK, SessionEvent, WorkSession,
)

logger = structlog.get_logger()

# Capabilities a readonly session may never exercise. Everything that writes,
# sends, executes, or reaches out.
WRITE_CAPABILITIES = frozenset({
    "shell.execute", "message.send", "file.write", "automation.run", "net.fetch",
})


class SessionError(Exception):
    """Invalid session operation. Message is user-facing."""


def _now() -> datetime:
    return datetime.utcnow()


def _to_dict(s: WorkSession) -> Dict[str, Any]:
    return {
        "id": s.id, "project_id": s.project_id, "title": s.title, "kind": s.kind,
        "permission_mode": s.permission_mode, "state": s.state,
        "checkpoint": s.checkpoint or {}, "revision": s.revision or 0,
        "workspace_roots": s.workspace_roots or [], "model": s.model,
        "note": s.note, "error": s.error,
        "suspended_at": s.suspended_at.isoformat() if s.suspended_at else None,
        "resumed_at": s.resumed_at.isoformat() if s.resumed_at else None,
        "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def _event(db: DatabaseManager, session_id: str, event: str, message: str = "",
           **metadata: Any) -> None:
    with db.get_session() as s:
        s.add(SessionEvent(id=str(uuid.uuid4()), session_id=session_id,
                           event=event, message=message[:1000],
                           extra_metadata=metadata or {}))
        s.commit()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def create(db: DatabaseManager, project_id: str, title: str,
           kind: str = "general", permission_mode: str = "ask",
           workspace_roots: Optional[List[str]] = None,
           model: Optional[str] = None) -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise SessionError("Give the session a title.")
    if permission_mode not in PERMISSION_MODES:
        raise SessionError(
            f"Permission mode must be one of: {', '.join(PERMISSION_MODES)}"
        )

    session_id = str(uuid.uuid4())
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise SessionError("Project not found.")
        s.add(WorkSession(
            id=session_id, project_id=project_id, title=title[:300], kind=kind,
            permission_mode=permission_mode, state="active",
            workspace_roots=workspace_roots or [], model=model,
            checkpoint={}, revision=0,
        ))
        s.commit()

    _event(db, session_id, "started", title, mode=permission_mode)
    logger.info("session_created", id=session_id, mode=permission_mode)
    return get(db, session_id)


def get(db: DatabaseManager, session_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        row = s.get(WorkSession, session_id)
        return _to_dict(row) if row else None


def list_sessions(db: DatabaseManager, project_id: str,
                  state: Optional[str] = None) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        q = s.query(WorkSession).filter(WorkSession.project_id == project_id)
        if state:
            q = q.filter(WorkSession.state == state)
        return [_to_dict(r) for r in
                q.order_by(WorkSession.last_active_at.desc()).limit(100).all()]


def checkpoint(db: DatabaseManager, session_id: str,
               state: Dict[str, Any]) -> Dict[str, Any]:
    """Save caller state. Merged, so a partial update does not erase the rest."""
    with db.get_session() as s:
        row = s.get(WorkSession, session_id)
        if not row:
            raise SessionError("Session not found.")
        if row.state in ("completed", "failed"):
            raise SessionError(f"This session is {row.state} and cannot be updated.")
        row.checkpoint = {**(row.checkpoint or {}), **(state or {})}
        row.revision = (row.revision or 0) + 1
        row.last_active_at = _now()
        s.commit()
        return _to_dict(row)


def suspend(db: DatabaseManager, session_id: str,
            note: str = "") -> Dict[str, Any]:
    with db.get_session() as s:
        row = s.get(WorkSession, session_id)
        if not row:
            raise SessionError("Session not found.")
        if row.state != "active":
            raise SessionError(f"Only an active session can be suspended (this is {row.state}).")
        row.state = "suspended"
        row.suspended_at = _now()
        row.note = (note or row.note or "")[:2000]
        s.commit()
    _event(db, session_id, "suspended", note)
    return get(db, session_id)


def resume(db: DatabaseManager, session_id: str) -> Dict[str, Any]:
    """Wake a suspended session, reporting how long it slept."""
    with db.get_session() as s:
        row = s.get(WorkSession, session_id)
        if not row:
            raise SessionError("Session not found.")
        if row.state == "active":
            return _to_dict(row)          # resuming a live session is a no-op
        if row.state in ("completed", "failed"):
            raise SessionError(f"This session is {row.state} and cannot be resumed.")
        slept = (_now() - row.suspended_at).total_seconds() if row.suspended_at else 0
        row.state = "active"
        row.resumed_at = _now()
        row.last_active_at = _now()
        s.commit()
        out = _to_dict(row)
    _event(db, session_id, "resumed", f"after {int(slept)}s", slept_seconds=int(slept))
    return out


def finish(db: DatabaseManager, session_id: str, ok: bool = True,
           error: str = "") -> Dict[str, Any]:
    with db.get_session() as s:
        row = s.get(WorkSession, session_id)
        if not row:
            raise SessionError("Session not found.")
        row.state = "completed" if ok else "failed"
        row.error = (error or "")[:2000] or None
        row.last_active_at = _now()
        s.commit()
    _event(db, session_id, "completed" if ok else "failed", error)
    return get(db, session_id)


def set_mode(db: DatabaseManager, session_id: str, mode: str) -> Dict[str, Any]:
    if mode not in PERMISSION_MODES:
        raise SessionError(f"Permission mode must be one of: {', '.join(PERMISSION_MODES)}")
    with db.get_session() as s:
        row = s.get(WorkSession, session_id)
        if not row:
            raise SessionError("Session not found.")
        previous = row.permission_mode
        row.permission_mode = mode
        s.commit()
    _event(db, session_id, "mode_changed", f"{previous} -> {mode}",
           previous=previous, mode=mode)
    logger.info("session_mode_changed", id=session_id, mode=mode)
    return get(db, session_id)


def events(db: DatabaseManager, session_id: str,
           limit: int = 100) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(SessionEvent)
                .filter(SessionEvent.session_id == session_id)
                .order_by(SessionEvent.created_at.desc()).limit(limit).all())
        return [{
            "id": e.id, "event": e.event, "message": e.message,
            "metadata": e.extra_metadata or {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        } for e in rows]


def reconcile(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """After a restart, an 'active' session has nobody driving it.

    They are suspended rather than failed: the work is not lost, it is simply
    not running, and resuming is one click. Failing them would discard
    checkpoints that are still perfectly good.
    """
    with db.get_session() as s:
        rows = (s.query(WorkSession)
                .filter(WorkSession.project_id == project_id,
                        WorkSession.state == "active").all())
        ids = [r.id for r in rows]
        for r in rows:
            r.state = "suspended"
            r.suspended_at = _now()
            r.note = (r.note or "") or "Suspended automatically when Dobby restarted."
        if rows:
            s.commit()
    for sid in ids:
        _event(db, sid, "suspended", "Dobby restarted", automatic=True)
    if ids:
        logger.info("sessions_reconciled", count=len(ids))
    return {"suspended": len(ids)}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
async def gate(db: DatabaseManager, session_id: Optional[str], project_id: str,
               capability: str, target: str, title: str, detail: str = "",
               risk: str = "medium", **kwargs: Any) -> Dict[str, Any]:
    """Apply a session's permission mode, then defer to the Inbox.

    With no session this is exactly `inbox.require` — the mode is an extra
    constraint, never a replacement for asking.
    """
    from src.services import inbox_service as inbox

    session = get(db, session_id) if session_id else None
    mode = (session or {}).get("permission_mode", "ask")

    if session and session["state"] not in ("active",):
        return {"allowed": False, "reason": f"session is {session['state']}",
                "ask_id": None, "mode": mode}

    if mode == "readonly" and capability in WRITE_CAPABILITIES:
        # Checked before grants on purpose: a mode a grant could defeat would
        # be a setting that lies to the user.
        _event(db, session_id, "blocked", f"readonly refused {capability}",
               capability=capability, target=target)
        return {
            "allowed": False,
            "reason": "this session is read-only",
            "ask_id": None, "mode": mode,
        }

    if mode == "unattended" and risk in UNATTENDED_AUTO_RISK:
        _event(db, session_id, "auto_approved", title,
               capability=capability, target=target, risk=risk)
        return {"allowed": True, "reason": "unattended: low risk",
                "ask_id": None, "mode": mode}

    verdict = await inbox.require(
        db, project_id, capability, target, title, detail=detail, risk=risk,
        **kwargs,
    )
    if session_id:
        _event(db, session_id, "gated",
               f"{capability} {target}: {verdict['reason']}",
               allowed=verdict["allowed"], capability=capability)
    return {**verdict, "mode": mode}
