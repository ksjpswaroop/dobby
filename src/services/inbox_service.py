"""
The approval gate and the Inbox.

`require()` is the whole point of this module. Any code about to do something
consequential calls it and gets back one of three answers:

    allowed   — a standing grant covers this; proceed
    approved  — the user said yes just now
    denied    — do not proceed

Everything else here exists to serve that call: grants so the user is not asked
the same question forever, expiry so an unanswered ask cannot wedge a caller,
and the Inbox so a question raised by a background job at 3am is still
answerable at 9am.

Design notes:

* **Parked, not blocking.** An ask is a database row first and a wait second.
  `require()` can wait on it, but nothing is lost if the waiter dies — the row
  is still there, still answerable, and the answer is still recorded.
* **Deny by default on timeout.** An unanswered approval must never become an
  approval. Silence is not consent.
* **Grants are narrow.** capability + target, never "trust this agent".
"""

from __future__ import annotations

import asyncio
import fnmatch
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

from src.db.inbox_models import (
    ASK_KINDS, ASK_STATES, CAPABILITIES, RISK_LEVELS, Ask, Grant,
)
from src.db.schema import DatabaseManager, Project

logger = structlog.get_logger()

DEFAULT_TIMEOUT = 300          # 5 minutes before an awaited ask gives up
DEFAULT_EXPIRY_HOURS = 24
POLL_INTERVAL = 0.5

# Waiters keyed by ask id, so an answer arriving over HTTP wakes the caller
# immediately instead of waiting for the next poll.
_waiters: Dict[str, asyncio.Event] = {}


class InboxError(Exception):
    """Invalid ask or grant. Message is user-facing."""


def _now() -> datetime:
    return datetime.utcnow()


def _ask_dict(a: Ask) -> Dict[str, Any]:
    return {
        "id": a.id, "project_id": a.project_id, "kind": a.kind,
        "capability": a.capability, "target": a.target, "title": a.title,
        "detail": a.detail, "risk": a.risk, "options": a.options or [],
        "state": a.state, "answer": a.answer, "answered_by": a.answered_by,
        "answered_at": a.answered_at.isoformat() if a.answered_at else None,
        "source": a.source, "source_id": a.source_id, "run_id": a.run_id,
        "awaited": bool(a.awaited),
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _grant_dict(g: Grant) -> Dict[str, Any]:
    return {
        "id": g.id, "capability": g.capability, "target": g.target,
        "note": g.note, "granted_by": g.granted_by, "use_count": g.use_count or 0,
        "expires_at": g.expires_at.isoformat() if g.expires_at else None,
        "last_used_at": g.last_used_at.isoformat() if g.last_used_at else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------
def _target_matches(pattern: str, target: str) -> bool:
    """Whether a grant's target covers an actual target.

    Wildcards are allowed but a bare "*" is not treated specially here — the
    caller decides whether to offer that, and `grant()` refuses it outright.
    """
    if not pattern:
        return not target
    return pattern == target or fnmatch.fnmatch(target, pattern)


def find_grant(db: DatabaseManager, project_id: str, capability: str,
               target: str) -> Optional[Dict[str, Any]]:
    """An active grant covering this action, if one exists."""
    now = _now()
    with db.get_session() as s:
        rows = (s.query(Grant)
                .filter(Grant.project_id == project_id,
                        Grant.capability == capability,
                        Grant.revoked_at.is_(None))
                .all())
        for g in rows:
            if g.expires_at and g.expires_at <= now:
                continue
            if _target_matches(g.target, target):
                g.use_count = (g.use_count or 0) + 1
                g.last_used_at = now
                s.commit()
                return _grant_dict(g)
    return None


def grant(db: DatabaseManager, project_id: str, capability: str, target: str,
          note: str = "", hours: Optional[int] = None) -> Dict[str, Any]:
    if capability not in CAPABILITIES:
        raise InboxError(f"Unknown capability. One of: {', '.join(CAPABILITIES)}")
    target = (target or "").strip()
    if target == "*":
        # A blanket grant defeats the entire mechanism. Refuse it rather than
        # let one careless click disable every future check.
        raise InboxError(
            "A grant for '*' would approve every target. Scope it to a specific "
            "host, command, or channel."
        )
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise InboxError("Project not found.")
        g = Grant(
            id=str(uuid.uuid4()), project_id=project_id, capability=capability,
            target=target, note=note[:500],
            expires_at=_now() + timedelta(hours=hours) if hours else None,
        )
        s.add(g)
        s.commit()
        out = _grant_dict(g)
    logger.info("grant_created", capability=capability, target=target)
    return out


def list_grants(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    now = _now()
    with db.get_session() as s:
        rows = (s.query(Grant)
                .filter(Grant.project_id == project_id, Grant.revoked_at.is_(None))
                .order_by(Grant.created_at.desc()).all())
        return [_grant_dict(g) for g in rows
                if not (g.expires_at and g.expires_at <= now)]


def revoke_grant(db: DatabaseManager, grant_id: str) -> bool:
    with db.get_session() as s:
        g = s.get(Grant, grant_id)
        if not g or g.revoked_at:
            return False
        g.revoked_at = _now()
        s.commit()
    logger.info("grant_revoked", grant_id=grant_id)
    return True


# ---------------------------------------------------------------------------
# Asks
# ---------------------------------------------------------------------------
def create_ask(db: DatabaseManager, project_id: str, title: str,
               capability: Optional[str] = None, target: str = "",
               kind: str = "approval", detail: str = "", risk: str = "medium",
               options: Optional[List[str]] = None, source: str = "manual",
               source_id: Optional[str] = None, run_id: Optional[str] = None,
               expiry_hours: int = DEFAULT_EXPIRY_HOURS,
               awaited: bool = False) -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise InboxError("An ask needs a title.")
    if kind not in ASK_KINDS:
        raise InboxError(f"Unknown ask kind. One of: {', '.join(ASK_KINDS)}")
    if capability and capability not in CAPABILITIES:
        raise InboxError(f"Unknown capability. One of: {', '.join(CAPABILITIES)}")
    if risk not in RISK_LEVELS:
        risk = "medium"

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise InboxError("Project not found.")
        a = Ask(
            id=str(uuid.uuid4()), project_id=project_id, kind=kind,
            capability=capability, target=(target or "")[:500], title=title[:300],
            detail=(detail or "")[:4000], risk=risk, options=options or [],
            source=source, source_id=source_id, run_id=run_id, awaited=awaited,
            expires_at=_now() + timedelta(hours=expiry_hours) if expiry_hours else None,
        )
        s.add(a)
        s.commit()
        out = _ask_dict(a)

    _waiters.setdefault(out["id"], asyncio.Event())
    logger.info("ask_created", id=out["id"], capability=capability, risk=risk)
    return out


async def notify_mirror(db: DatabaseManager, ask: Dict[str, Any]) -> None:
    """Post a new ask into the configured messaging channel (OW row 18).

    Deliberately does not go through `messaging_service.reply()`'s approval
    gate: the mirror *target* was explicitly configured by the user in
    Settings, and that configuration is the consent. Re-asking permission to
    send the notification that something needs a decision would be circular —
    a notification is informational, not an action taken on the user's
    behalf. Failure here is always best-effort: a messaging outage must never
    block the ask itself from being created and usable in the Inbox.
    """
    from src.settings import get_settings

    settings = get_settings()
    connector_name = getattr(settings, "inbox_mirror_connector", "") or ""
    channel = getattr(settings, "inbox_mirror_channel", "") or ""
    if not connector_name or not channel:
        return

    try:
        from src.services import messaging_service

        connector = messaging_service.get_connector(connector_name)
        if not connector.configured:
            return
        risk_tag = f"[{ask['risk']}]" if ask.get("risk") else ""
        text = f"🔔 {risk_tag} Approval needed: {ask['title']}"
        if ask.get("detail"):
            text += f"\n{ask['detail'][:300]}"
        await connector.send(channel, text)
    except Exception as e:  # noqa: BLE001 — a mirror failure must never break the ask
        logger.warning("inbox_mirror_failed", connector=connector_name, error=str(e))


def get_ask(db: DatabaseManager, ask_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        a = s.get(Ask, ask_id)
        return _ask_dict(a) if a else None


def list_asks(db: DatabaseManager, project_id: str,
              state: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    expire_overdue(db)
    with db.get_session() as s:
        q = s.query(Ask).filter(Ask.project_id == project_id)
        if state:
            q = q.filter(Ask.state == state)
        rows = q.order_by(Ask.created_at.desc()).limit(limit).all()
        return [_ask_dict(a) for a in rows]


def pending_count(db: DatabaseManager, project_id: str) -> int:
    expire_overdue(db)
    with db.get_session() as s:
        return (s.query(Ask)
                .filter(Ask.project_id == project_id, Ask.state == "pending").count())


def answer_ask(db: DatabaseManager, ask_id: str, approved: bool,
               answer: str = "", answered_by: str = "user",
               remember_hours: Optional[int] = None) -> Dict[str, Any]:
    """Resolve an ask, optionally turning the decision into a standing grant."""
    with db.get_session() as s:
        a = s.get(Ask, ask_id)
        if not a:
            raise InboxError("Ask not found.")
        if a.state != "pending":
            raise InboxError(f"This was already {a.state}.")
        a.state = "approved" if approved else "denied"
        a.answer = (answer or "")[:2000]
        a.answered_by = answered_by
        a.answered_at = _now()
        project_id, capability, target = a.project_id, a.capability, a.target
        s.commit()
        out = _ask_dict(a)

    # "Yes, and stop asking" — only ever on approval, never on denial.
    if approved and remember_hours is not None and capability:
        try:
            out["grant"] = grant(db, project_id, capability, target,
                                 note=f"From ask: {out['title'][:100]}",
                                 hours=remember_hours or None)
        except InboxError as e:
            out["grant_error"] = str(e)

    ev = _waiters.get(ask_id)
    if ev:
        ev.set()
    logger.info("ask_answered", id=ask_id, approved=approved)
    return out


def cancel_ask(db: DatabaseManager, ask_id: str) -> bool:
    with db.get_session() as s:
        a = s.get(Ask, ask_id)
        if not a or a.state != "pending":
            return False
        a.state = "cancelled"
        a.answered_at = _now()
        s.commit()
    ev = _waiters.get(ask_id)
    if ev:
        ev.set()
    return True


def expire_overdue(db: DatabaseManager) -> int:
    """Mark past-deadline asks expired. Expiry is a denial, never an approval."""
    now = _now()
    with db.get_session() as s:
        rows = (s.query(Ask)
                .filter(Ask.state == "pending", Ask.expires_at.isnot(None),
                        Ask.expires_at <= now).all())
        for a in rows:
            a.state = "expired"
            ev = _waiters.get(a.id)
            if ev:
                ev.set()
        if rows:
            s.commit()
        return len(rows)


def reconcile(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """Re-establish waiters after a restart (OW row 19).

    A process that died while waiting leaves `awaited=True` on a row nobody is
    listening to. Those are still perfectly answerable — they just no longer
    have anyone to wake — so the flag is cleared and the ask stays in the Inbox
    rather than looking permanently in-flight.
    """
    expired = expire_overdue(db)
    with db.get_session() as s:
        stranded = (s.query(Ask)
                    .filter(Ask.project_id == project_id, Ask.state == "pending",
                            Ask.awaited.is_(True)).all())
        for a in stranded:
            a.awaited = False
        count = len(stranded)
        if count:
            s.commit()
    if count or expired:
        logger.info("inbox_reconciled", stranded=count, expired=expired)
    return {"reconnected": count, "expired": expired}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
async def require(db: DatabaseManager, project_id: str, capability: str,
                  target: str, title: str, detail: str = "",
                  risk: str = "medium", timeout: int = DEFAULT_TIMEOUT,
                  source: str = "manual", source_id: Optional[str] = None,
                  run_id: Optional[str] = None) -> Dict[str, Any]:
    """Gate a consequential action behind a grant or a human decision.

    Returns ``{"allowed": bool, "reason": str, "ask_id": str | None}``.

    Denies on timeout. An approval that nobody gave is not an approval, and a
    caller that silently proceeds after five minutes of silence is worse than
    one that gives up.
    """
    existing = find_grant(db, project_id, capability, target)
    if existing:
        return {"allowed": True, "reason": "standing grant",
                "grant_id": existing["id"], "ask_id": None}

    ask = create_ask(
        db, project_id, title, capability=capability, target=target,
        kind="approval", detail=detail, risk=risk, source=source,
        source_id=source_id, run_id=run_id, awaited=True,
    )
    ask_id = ask["id"]
    event = _waiters.setdefault(ask_id, asyncio.Event())
    await notify_mirror(db, ask)

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        # The row stays pending and answerable; only this waiter gives up.
        with db.get_session() as s:
            a = s.get(Ask, ask_id)
            if a:
                a.awaited = False
                s.commit()
        logger.info("ask_timed_out", id=ask_id)
        return {"allowed": False, "reason": "timed out waiting for approval",
                "ask_id": ask_id}
    finally:
        _waiters.pop(ask_id, None)

    final = get_ask(db, ask_id) or {}
    allowed = final.get("state") == "approved"
    return {
        "allowed": allowed,
        "reason": final.get("state", "unknown"),
        "answer": final.get("answer", ""),
        "ask_id": ask_id,
    }
