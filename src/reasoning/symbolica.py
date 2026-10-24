"""
Symbolica — optional escalation to a full symbolic engine.

`src.reasoning.logic` decides classical *propositional* logic completely and
offline, which covers most of what Dobby needs. Symbolica adds what that cannot
do: first-order logic, Fitch-style proof objects, causal DAG queries, deontic
and equational reasoning, and natural-language formalization.

It is strictly optional. Every call degrades to the local engine when no server
is configured or the server is unreachable, so reasoning never becomes a hard
dependency on a network service — the same rule the search layer follows.

API contract: https://github.com/ksjpswaroop/symbolica — `POST /v1/verify/claim`
and `POST /v1/formalize`, both returning a fixed envelope
``{ok, verdict, data, error, request_id, usage}``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx
import structlog

logger = structlog.get_logger()

TIMEOUT = 20.0


@dataclass
class SymbolicaResult:
    """A verdict from the symbolic engine, plus how it was reached."""

    verdict: str                                  # valid | invalid | unknown
    proof: str = ""
    countermodel: Optional[Dict[str, Any]] = None
    engine: str = ""
    elapsed_ms: int = 0
    error: str = ""
    available: bool = True

    @property
    def ok(self) -> bool:
        return self.verdict == "valid"


@dataclass
class Formalization:
    """A natural-language claim translated into a sequent."""

    premises: List[str] = field(default_factory=list)
    conclusion: str = ""
    glossary: Dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.conclusion) and not self.error


def _config() -> Dict[str, str]:
    from src.settings import get_settings

    s = get_settings()
    return {
        "url": (getattr(s, "symbolica_url", "") or "").rstrip("/"),
        "key": getattr(s, "symbolica_api_key", "") or "",
    }


def is_configured() -> bool:
    return bool(_config()["url"])


async def _post(path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cfg = _config()
    if not cfg["url"]:
        return None
    headers = {"Content-Type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = f"Bearer {cfg['key']}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{cfg['url']}{path}", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()


async def verify_claim(premises: Sequence[str], conclusion: str,
                       logic: Optional[str] = None) -> SymbolicaResult:
    """Machine-check a sequent. Falls back to the local engine when unavailable.

    The fallback is not a silent downgrade: `engine` names which one answered,
    so a caller — and the audit trail — can tell a first-order verdict from a
    propositional one.
    """
    payload: Dict[str, Any] = {"premises": list(premises), "conclusion": conclusion}
    if logic:
        payload["logic"] = logic

    try:
        body = await _post("/v1/verify/claim", payload)
    except Exception as e:
        logger.warning("symbolica_unreachable", error=str(e))
        body = None

    if body is None:
        return _local_fallback(premises, conclusion,
                               "" if is_configured() else "not configured")

    if not body.get("ok"):
        err = (body.get("error") or {})
        msg = err.get("message") or err.get("code") or "verification failed"
        return _local_fallback(premises, conclusion, str(msg))

    data = body.get("data") or {}
    usage = body.get("usage") or {}
    return SymbolicaResult(
        verdict=body.get("verdict") or "unknown",
        proof=str(data.get("proof") or ""),
        countermodel=data.get("countermodel"),
        engine=str(usage.get("engine") or "symbolica"),
        elapsed_ms=int(usage.get("elapsed_ms") or 0),
    )


def _local_fallback(premises: Sequence[str], conclusion: str,
                    note: str) -> SymbolicaResult:
    from src.reasoning import logic as local

    v = local.check(list(premises), conclusion)
    return SymbolicaResult(
        verdict=v.verdict,
        countermodel=v.countermodel,
        engine="local-truth-table",
        error=note,
        available=False,
    )


async def formalize(text: str) -> Formalization:
    """Translate natural language into a sequent. Symbolica-only.

    There is no local fallback: turning prose into logic needs a model, and
    guessing at it would produce exactly the confident-but-wrong output the
    reasoning layer exists to prevent.
    """
    try:
        body = await _post("/v1/formalize", {"text": text})
    except Exception as e:
        return Formalization(error=f"Symbolica unreachable: {e}")

    if body is None:
        return Formalization(error="No Symbolica server configured.")
    if not body.get("ok"):
        err = (body.get("error") or {})
        return Formalization(error=str(err.get("code") or "formalization failed"))

    data = body.get("data") or {}
    return Formalization(
        premises=[str(p) for p in (data.get("premises") or [])],
        conclusion=str(data.get("conclusion") or ""),
        glossary={str(k): str(v) for k, v in (data.get("glossary") or {}).items()},
    )


async def health() -> Dict[str, Any]:
    """Whether the symbolic engine is reachable, for Settings."""
    if not is_configured():
        return {"configured": False, "reachable": False}
    try:
        cfg = _config()
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.get(f"{cfg['url']}/v1/health")
            return {"configured": True, "reachable": r.status_code == 200}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)}
