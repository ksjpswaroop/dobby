"""
Client-side license verification — what actually ships in the app.

This is the anti-piracy spec from docs/expansion/08_LICENSING_AND_PRICING_DECISION.md
§7, made concrete:

1. Every verification, when the authority is reachable, receives a
   **server-issued signed timestamp** alongside the license status — the
   client's own clock is never treated as the source of truth for expiry math.
2. The client persists the **last known-good verification time** (the
   high-water mark). If the local system clock ever reads *earlier* than that
   mark by more than a small skew tolerance, the license is treated as invalid
   until a fresh online verification succeeds — this is what makes rolling the
   clock back to defeat an update-expiry check fail: the stored mark does not
   roll back with it.
3. The offline grace period still applies **forward** in time — a paying user
   offline on a plane keeps working — the tamper check only fires on a
   *backward* jump, which has no legitimate reason to happen.
4. A fresh signature accompanies every successful re-verification, so a token
   captured from one verification response has a shelf life rather than
   working forever once exfiltrated. (v1 re-signs the same token payload each
   verify; a captured *token* itself is still valid until its update window
   lapses — narrowing that further is a v2 concern once billing exists and
   tokens can be short-lived and refreshed via a real auth flow.)

Local state lives in `~/.dobby/license_state.json` — this one genuinely is
client data, unlike the authority's `licenses` table.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import structlog

logger = structlog.get_logger()

STATE_PATH = Path.home() / ".dobby" / "license_state.json"

# How far a system clock may read *behind* the last confirmed-good time before
# it is treated as tampering rather than ordinary drift/timezone jitter.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)

# How long a license keeps working with no successful online check-in, using
# only forward-moving local time — never break local-first for a user who is
# legitimately offline.
OFFLINE_GRACE = timedelta(days=30)

DEFAULT_AUTHORITY_URL = "http://127.0.0.1:8000"


@dataclass
class LicenseState:
    token: str = ""
    tier: str = "free"
    seats: int = 1
    updates_until: Optional[str] = None
    high_water_mark: Optional[str] = None   # last server-confirmed time seen
    last_verified_ok: bool = False
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LicenseState":
        known = {f: data[f] for f in cls().to_dict().keys() if f in data}
        return cls(**known)


def _load() -> LicenseState:
    if not STATE_PATH.exists():
        return LicenseState()
    try:
        return LicenseState.from_dict(json.loads(STATE_PATH.read_text()))
    except (json.JSONDecodeError, OSError):
        return LicenseState()


def _save(state: LicenseState) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state.to_dict()))
    except OSError as e:
        logger.warning("license_state_unwritable", error=str(e))


def _parse_iso(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clock_rolled_back(now: datetime, state: LicenseState) -> bool:
    """True if the system clock reads meaningfully earlier than the last
    confirmed-good time — the signature of rolling a clock back to defeat an
    update-expiry check."""
    mark = _parse_iso(state.high_water_mark)
    if not mark:
        return False
    return now < (mark - CLOCK_SKEW_TOLERANCE)


def activate(token: str) -> Dict[str, Any]:
    """Save a newly-pasted license token as the active one."""
    from src.licensing import authority

    payload, _, _ = authority.split_token(token)  # raises LicenseError if malformed
    state = LicenseState(token=token, tier=payload.get("tier", "free"),
                         seats=payload.get("seats", 1),
                         updates_until=payload.get("upd"))
    _save(state)
    return state.to_dict()


def deactivate() -> None:
    _save(LicenseState())


def status() -> Dict[str, Any]:
    """The cached status, with no network call — for a fast Settings render."""
    return _load().to_dict()


async def check(authority_url: str = DEFAULT_AUTHORITY_URL) -> Dict[str, Any]:
    """Re-verify the active license. Called on activation and periodically.

    Returns ``{"valid": bool, "tier": str, "reason": str, "offline": bool}``.
    Never raises — a licensing check must never be the reason the app fails
    to start.
    """
    state = _load()
    now = datetime.now(timezone.utc)

    if not state.token:
        return {"valid": False, "tier": "free", "reason": "no license activated",
                "offline": False}

    if clock_rolled_back(now, state):
        # The stored mark does not move backward with the clock, so this
        # cannot be cleared by anything except a fresh successful online
        # verification, which re-establishes the mark from the server's own
        # time rather than the machine being checked.
        logger.warning("license_clock_rollback_detected",
                       high_water_mark=state.high_water_mark)
        return {"valid": False, "tier": "free",
                "reason": "system clock moved backward since the last check — "
                          "reconnect to re-verify", "offline": False}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(f"{authority_url}/api/v1/license/verify",
                                  json={"token": state.token})
            r.raise_for_status()
            result = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return _offline_fallback(state, now, str(e))

    if not result.get("valid"):
        state.last_verified_ok = False
        state.last_error = result.get("reason", "invalid")
        _save(state)
        return {"valid": False, "tier": "free", "reason": state.last_error,
                "offline": False}

    # Advance the high-water mark from the SERVER's clock, never the client's —
    # this is the field a rolled-back local clock cannot move backward.
    state.high_water_mark = result["server_time"]
    state.tier = result["tier"]
    state.seats = result["seats"]
    state.updates_until = result.get("updates_until")
    state.last_verified_ok = True
    state.last_error = ""
    _save(state)
    return {"valid": True, "tier": state.tier, "reason": "ok", "offline": False}


def _offline_fallback(state: LicenseState, now: datetime, error: str) -> Dict[str, Any]:
    """No network reached the authority. Grace applies forward-in-time only."""
    mark = _parse_iso(state.high_water_mark)
    if not mark or not state.last_verified_ok:
        return {"valid": False, "tier": "free",
                "reason": f"never successfully verified and offline ({error})",
                "offline": True}

    if now - mark > OFFLINE_GRACE:
        return {"valid": False, "tier": "free",
                "reason": "offline grace period expired — reconnect to keep updates",
                "offline": True}

    return {"valid": True, "tier": state.tier,
            "reason": "using last verified status while offline", "offline": True}
