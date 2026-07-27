"""
Message routing, subscriptions, and the dead-letter store (OW 18, 33-36, 38).

What happens to an inbound message:

1. **Verify** the signature. An unverified webhook is dropped and counted —
   never processed, never answered.
2. **Route** it. A subscribed channel or a direct message reaches the app; a
   mention always does. Anything else is *dead-lettered*, not discarded.
3. **Gate** the reply. Sending on the user's behalf is `message.send`, which
   goes through the Inbox like everything else — except in a thread the user
   already started, which is pre-approved (OW 34) because replying where you
   were spoken to is not a surprise.

The dead-letter store is the part that earns trust. A chat integration that
silently drops what it does not understand is impossible to debug: you cannot
tell whether nothing happened because nothing was said. Every unrouted message
is kept with the reason, and the recent buffer (OW 36) means a restart does not
lose the last few minutes of context.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import structlog

from src.connectors.base import Connector, ConnectorError, Message, build
from src.db.schema import DatabaseManager

logger = structlog.get_logger()

CONFIG_PATH = Path.home() / ".dobby" / "connectors.json"
DEAD_LETTER_PATH = Path.home() / ".dobby" / "dead_letters.json"

MAX_DEAD_LETTERS = 500
RECENT_BUFFER = 100

# Messages seen recently, per connector, so a restart keeps context (OW 36).
_recent: Dict[str, Deque[Dict[str, Any]]] = {}


class MessagingError(Exception):
    """Message is user-facing."""


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("messaging_config_unreadable", path=str(path))
    return default


def _save(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        path.chmod(0o600)          # these files hold bot tokens
    except OSError as e:
        raise MessagingError(f"Could not save: {e}")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _config() -> Dict[str, Any]:
    return _load(CONFIG_PATH, {"connectors": {}, "subscriptions": {}})


def configure(name: str, credentials: Dict[str, str]) -> Dict[str, Any]:
    if name not in ("slack", "telegram"):
        raise MessagingError(f"Unknown connector: {name}")
    cfg = _config()
    existing = cfg["connectors"].get(name, {})
    # Merge so setting one field does not wipe the others.
    cfg["connectors"][name] = {**existing, **{k: v for k, v in credentials.items() if v}}
    _save(CONFIG_PATH, cfg)
    logger.info("connector_configured", name=name)
    return status(name)


def get_connector(name: str) -> Connector:
    return build(name, _config()["connectors"].get(name, {}))


def status(name: Optional[str] = None) -> Dict[str, Any]:
    cfg = _config()
    names = [name] if name else list(("slack", "telegram"))
    out = {}
    for n in names:
        conn = build(n, cfg["connectors"].get(n, {}))
        out[n] = {
            "configured": conn.configured,
            "missing": conn.missing_credentials(),
            "subscriptions": cfg["subscriptions"].get(n, []),
            # Credentials are never echoed back — only whether they are set.
            "required": conn.required_credentials,
        }
    return out if not name else out[name]


def subscribe(name: str, channel: str) -> List[str]:
    cfg = _config()
    subs = set(cfg["subscriptions"].get(name, []))
    subs.add(channel)
    cfg["subscriptions"][name] = sorted(subs)
    _save(CONFIG_PATH, cfg)
    return cfg["subscriptions"][name]


def unsubscribe(name: str, channel: str) -> List[str]:
    cfg = _config()
    subs = [c for c in cfg["subscriptions"].get(name, []) if c != channel]
    cfg["subscriptions"][name] = subs
    _save(CONFIG_PATH, cfg)
    return subs


def subscriptions(name: str) -> List[str]:
    return _config()["subscriptions"].get(name, [])


# ---------------------------------------------------------------------------
# Dead letters (OW 38)
# ---------------------------------------------------------------------------
def dead_letter(message: Optional[Message], reason: str,
                raw: Optional[Dict[str, Any]] = None) -> None:
    """Keep what could not be routed, with why."""
    rows = _load(DEAD_LETTER_PATH, [])
    rows.append({
        "id": str(uuid.uuid4()),
        "reason": reason,
        "message": message.to_dict() if message else None,
        "raw_preview": json.dumps(raw or {})[:500] if raw else "",
        "at": datetime.utcnow().isoformat(),
    })
    try:
        _save(DEAD_LETTER_PATH, rows[-MAX_DEAD_LETTERS:])
    except MessagingError:
        pass                       # never let bookkeeping break delivery
    logger.info("message_dead_lettered", reason=reason)


def dead_letters(limit: int = 100) -> List[Dict[str, Any]]:
    return list(reversed(_load(DEAD_LETTER_PATH, [])))[:limit]


def clear_dead_letters() -> int:
    rows = _load(DEAD_LETTER_PATH, [])
    _save(DEAD_LETTER_PATH, [])
    return len(rows)


def recent(name: str, limit: int = 20) -> List[Dict[str, Any]]:
    """The recent-channel buffer (OW 36)."""
    return list(_recent.get(name, deque()))[-limit:]


def _remember(message: Message) -> None:
    buf = _recent.setdefault(message.connector, deque(maxlen=RECENT_BUFFER))
    buf.append(message.to_dict())


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------
def should_handle(message: Message, subs: List[str]) -> tuple[bool, str]:
    """Whether a message is for us, and why."""
    if message.mentioned:
        return True, "mentioned"
    if message.is_direct:
        return True, "direct message"
    if message.channel in subs:
        return True, "subscribed channel"
    return False, "not mentioned, not a DM, and not a subscribed channel"


async def handle_webhook(db: DatabaseManager, project_id: str, name: str,
                         body: bytes, headers: Dict[str, str],
                         payload: Dict[str, Any]) -> Dict[str, Any]:
    """Verify, route, and act on an inbound webhook."""
    connector = get_connector(name)
    if not connector.configured:
        dead_letter(None, f"{name} is not configured", payload)
        raise MessagingError(f"{name} is not configured.")

    if not connector.verify(body, {k.lower(): v for k, v in headers.items()}):
        # Not dead-lettered: an unverified request is not a message, it is an
        # unauthenticated stranger. Storing its contents would be the bug.
        logger.warning("webhook_signature_invalid", connector=name)
        raise MessagingError("Signature verification failed.")

    # Slack's endpoint handshake.
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    message = connector.parse(payload)
    if not message:
        return {"ignored": True, "reason": "not a message event"}

    _remember(message)
    handle, reason = should_handle(message, subscriptions(name))
    if not handle:
        dead_letter(message, reason, payload)
        return {"handled": False, "reason": reason}

    return {"handled": True, "reason": reason, "message": message.to_dict()}


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------
async def reply(db: DatabaseManager, project_id: str, name: str, channel: str,
                text: str, thread: Optional[str] = None,
                in_reply_to: Optional[Message] = None) -> Dict[str, Any]:
    """Send a message, gated unless it is a reply where we were addressed.

    OW 34: replying in a thread the user started by @mentioning us is
    pre-approved. Asking permission to answer a direct question would make the
    integration unusable, and the user has already indicated intent by speaking
    to it. Anything else — a new message, a different channel — still asks.
    """
    connector = get_connector(name)
    if not connector.configured:
        raise MessagingError(f"{name} is not configured.")

    pre_approved = bool(
        in_reply_to
        and (in_reply_to.mentioned or in_reply_to.is_direct)
        and in_reply_to.channel == channel
    )

    if not pre_approved:
        from src.services import inbox_service as inbox

        verdict = await inbox.require(
            db, project_id, "message.send", f"{name}:{channel}",
            title=f"Send a message to {channel} on {name}?",
            detail=f"Dobby wants to send:\n\n{text[:600]}",
            risk="high", source="messaging", timeout=180,
        )
        if not verdict["allowed"]:
            return {"sent": False, "reason": verdict["reason"],
                    "ask_id": verdict.get("ask_id")}

    try:
        result = await connector.send(channel, text, thread)
    except ConnectorError as e:
        raise MessagingError(str(e))
    logger.info("message_sent", connector=name, channel=channel,
                pre_approved=pre_approved)
    return {"sent": True, "pre_approved": pre_approved, **result}


async def health() -> Dict[str, Any]:
    out = {}
    for name in ("slack", "telegram"):
        try:
            out[name] = await get_connector(name).health()
        except Exception as e:
            out[name] = {"ok": False, "reason": str(e)}
    return out
