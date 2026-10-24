"""
Webhooks, API keys, and recipes (100-Day Roadmap: D58, D59, D60).

**Webhook URLs go through the approval gate.** Posting project content to an
arbitrary host is exactly the kind of consequential, outward-facing action the
Inbox exists for, so registering a webhook to a non-loopback host requires a
`net.fetch` grant. The alternative — any code path that can create a webhook
can also exfiltrate the user's documents — is not acceptable in an app whose
whole promise is that data stays local.

**Deliveries are HMAC-signed** with a per-webhook secret so a receiver can
verify the request genuinely came from this install, and **every attempt is
recorded** including failures.

**API keys are stored hashed.** The plaintext is returned once at creation and
is unrecoverable afterwards.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import structlog

from src.db.integration_models import (
    API_SCOPES, RECIPE_ACTIONS, RECIPE_TRIGGERS, WEBHOOK_EVENTS,
    ApiKey, Recipe, Webhook, WebhookDelivery,
)
from src.db.schema import DatabaseManager, Project

logger = structlog.get_logger()

MAX_FAILURES_BEFORE_DISABLE = 10
DELIVERY_TIMEOUT = 10.0

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class IntegrationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Webhooks (D58)
# ---------------------------------------------------------------------------
def _is_loopback(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in LOOPBACK_HOSTS


async def create_webhook(db: DatabaseManager, project_id: str, url: str,
                         events: List[str], description: str = "") -> Dict[str, Any]:
    if not re.match(r"^https?://", url or "", re.I):
        raise IntegrationError("A webhook needs a full http(s) URL.")

    unknown = [e for e in events if e not in WEBHOOK_EVENTS]
    if unknown:
        raise IntegrationError(f"Unknown events: {', '.join(unknown)}. "
                               f"One of: {', '.join(WEBHOOK_EVENTS)}")
    if not events:
        raise IntegrationError("Subscribe to at least one event.")

    # Sending project content to a remote host is consequential and outward
    # facing; loopback is exempt because it never leaves the machine.
    if not _is_loopback(url):
        from src.services import inbox_service

        host = urlparse(url).hostname or url
        decision = await inbox_service.require(
            db, project_id, "net.fetch", host,
            title=f"Send project events to {host}?",
            detail=(f"A webhook would POST {', '.join(events)} events to {url}. "
                    "Document titles and ids leave this machine."),
            risk="high",
        )
        if decision not in ("allowed", "approved"):
            raise IntegrationError(
                f"Sending events to {host} was not approved.")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise IntegrationError("Project not found.")
        hook = Webhook(
            id=str(uuid.uuid4()), project_id=project_id, url=url,
            events=list(events), secret=secrets.token_hex(24),
            description=description[:300], active=1,
        )
        s.add(hook)
        s.commit()
        return _webhook_dict(hook, include_secret=True)


def _webhook_dict(hook: Webhook, include_secret: bool = False) -> Dict[str, Any]:
    out = {
        "id": hook.id, "url": hook.url, "events": hook.events or [],
        "active": bool(hook.active), "description": hook.description,
        "failure_count": hook.failure_count,
        "created_at": hook.created_at.isoformat() if hook.created_at else None,
        "last_fired_at": hook.last_fired_at.isoformat() if hook.last_fired_at else None,
    }
    if include_secret:
        # Shown once so the receiver can be configured to verify signatures.
        out["secret"] = hook.secret
    return out


def list_webhooks(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = s.query(Webhook).filter(Webhook.project_id == project_id).all()
        return [_webhook_dict(h) for h in rows]


def delete_webhook(db: DatabaseManager, webhook_id: str) -> bool:
    with db.get_session() as s:
        hook = s.get(Webhook, webhook_id)
        if not hook:
            return False
        for d in s.query(WebhookDelivery).filter(
                WebhookDelivery.webhook_id == webhook_id).all():
            s.delete(d)
        s.flush()
        s.delete(hook)
        s.commit()
        return True


def sign_payload(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


async def fire(db: DatabaseManager, project_id: str, event: str,
               payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deliver an event to every subscribed webhook. Never raises."""
    if event not in WEBHOOK_EVENTS:
        return {"delivered": 0, "skipped": "unknown event"}

    with db.get_session() as s:
        hooks = [h for h in s.query(Webhook)
                 .filter(Webhook.project_id == project_id, Webhook.active == 1).all()
                 if event in (h.events or [])]
        targets = [(h.id, h.url, h.secret) for h in hooks]

    if not targets:
        return {"delivered": 0}

    import httpx

    body_obj = {"event": event, "project_id": project_id,
                "sent_at": datetime.utcnow().isoformat(), "data": payload}
    body = json.dumps(body_obj, default=str)

    delivered, failed = 0, 0
    for hook_id, url, secret in targets:
        started = time.monotonic()
        status, ok, error = None, False, ""
        try:
            async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
                resp = await client.post(url, content=body, headers={
                    "Content-Type": "application/json",
                    "X-Dobby-Event": event,
                    "X-Dobby-Signature": f"sha256={sign_payload(secret, body)}",
                })
                status = resp.status_code
                ok = 200 <= resp.status_code < 300
                if not ok:
                    error = f"HTTP {resp.status_code}"
        except Exception as e:
            error = str(e)[:300]

        duration = int((time.monotonic() - started) * 1000)
        with db.get_session() as s:
            s.add(WebhookDelivery(
                id=str(uuid.uuid4()), webhook_id=hook_id, event=event,
                payload=body_obj, status_code=status, ok=1 if ok else 0,
                error=error, duration_ms=duration,
            ))
            hook = s.get(Webhook, hook_id)
            if hook:
                hook.last_fired_at = datetime.utcnow()
                if ok:
                    hook.failure_count = 0
                else:
                    hook.failure_count = (hook.failure_count or 0) + 1
                    # A permanently broken endpoint should stop being retried
                    # forever, but the row stays so the user can see why.
                    if hook.failure_count >= MAX_FAILURES_BEFORE_DISABLE:
                        hook.active = 0
                        logger.warning("webhook_disabled", webhook_id=hook_id)
            s.commit()

        delivered += 1 if ok else 0
        failed += 0 if ok else 1

    return {"delivered": delivered, "failed": failed, "targets": len(targets)}


def deliveries(db: DatabaseManager, webhook_id: str,
               limit: int = 20) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(WebhookDelivery)
                .filter(WebhookDelivery.webhook_id == webhook_id)
                .order_by(WebhookDelivery.created_at.desc()).limit(limit).all())
        return [{"id": d.id, "event": d.event, "status_code": d.status_code,
                 "ok": bool(d.ok), "error": d.error, "duration_ms": d.duration_ms,
                 "created_at": d.created_at.isoformat() if d.created_at else None}
                for d in rows]


# ---------------------------------------------------------------------------
# API keys (D59)
# ---------------------------------------------------------------------------
def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_api_key(db: DatabaseManager, name: str, scopes: List[str],
                   project_id: Optional[str] = None) -> Dict[str, Any]:
    """Mint a key. The plaintext is returned once and never stored."""
    name = (name or "").strip()
    if not name:
        raise IntegrationError("A key needs a name.")
    unknown = [s_ for s_ in scopes if s_ not in API_SCOPES]
    if unknown:
        raise IntegrationError(f"Unknown scopes: {', '.join(unknown)}. "
                               f"One of: {', '.join(API_SCOPES)}")
    if not scopes:
        raise IntegrationError("A key needs at least one scope.")

    plaintext = f"dob_{secrets.token_urlsafe(32)}"
    with db.get_session() as s:
        key = ApiKey(
            id=str(uuid.uuid4()), name=name[:120], key_hash=_hash_key(plaintext),
            prefix=plaintext[:12], scopes=list(scopes), project_id=project_id,
            active=1,
        )
        s.add(key)
        s.commit()
        out = _key_dict(key)

    out["key"] = plaintext
    out["warning"] = "This is the only time the key is shown. Store it now."
    return out


def _key_dict(key: ApiKey) -> Dict[str, Any]:
    return {
        "id": key.id, "name": key.name, "prefix": key.prefix,
        "scopes": key.scopes or [], "project_id": key.project_id,
        "active": bool(key.active), "use_count": key.use_count,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }


def list_api_keys(db: DatabaseManager) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        return [_key_dict(k) for k in
                s.query(ApiKey).order_by(ApiKey.created_at.desc()).all()]


def verify_api_key(db: DatabaseManager, plaintext: str,
                   required_scope: str = "read") -> Optional[Dict[str, Any]]:
    """Return the key record if valid and scoped, else None."""
    if not plaintext:
        return None
    with db.get_session() as s:
        key = (s.query(ApiKey)
               .filter(ApiKey.key_hash == _hash_key(plaintext),
                       ApiKey.active == 1).first())
        if not key:
            return None
        scopes = key.scopes or []
        if required_scope not in scopes and "admin" not in scopes:
            return None
        key.last_used_at = datetime.utcnow()
        key.use_count = (key.use_count or 0) + 1
        s.commit()
        return _key_dict(key)


def revoke_api_key(db: DatabaseManager, key_id: str) -> bool:
    with db.get_session() as s:
        key = s.get(ApiKey, key_id)
        if not key:
            return False
        key.active = 0
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Recipes (D60)
# ---------------------------------------------------------------------------
def create_recipe(db: DatabaseManager, project_id: str, name: str, trigger: str,
                  action: str, action_params: Optional[Dict[str, Any]] = None,
                  condition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise IntegrationError("A recipe needs a name.")
    if trigger not in RECIPE_TRIGGERS:
        raise IntegrationError(f"Unknown trigger. One of: {', '.join(RECIPE_TRIGGERS)}")
    if action not in RECIPE_ACTIONS:
        raise IntegrationError(f"Unknown action. One of: {', '.join(RECIPE_ACTIONS)}")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise IntegrationError("Project not found.")
        recipe = Recipe(
            id=str(uuid.uuid4()), project_id=project_id, name=name[:120],
            trigger=trigger, action=action,
            action_params=action_params or {}, condition=condition or {}, active=1,
        )
        s.add(recipe)
        s.commit()
        return _recipe_dict(recipe)


def _recipe_dict(r: Recipe) -> Dict[str, Any]:
    return {
        "id": r.id, "name": r.name, "trigger": r.trigger, "action": r.action,
        "action_params": r.action_params or {}, "condition": r.condition or {},
        "active": bool(r.active), "run_count": r.run_count,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
    }


def list_recipes(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        return [_recipe_dict(r) for r in
                s.query(Recipe).filter(Recipe.project_id == project_id).all()]


def delete_recipe(db: DatabaseManager, recipe_id: str) -> bool:
    with db.get_session() as s:
        r = s.get(Recipe, recipe_id)
        if not r:
            return False
        s.delete(r)
        s.commit()
        return True


def matches_condition(condition: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    """A recipe with no condition fires on every occurrence of its trigger."""
    if not condition:
        return True
    text = json.dumps(payload, default=str).lower()

    if "contains" in condition:
        if str(condition["contains"]).lower() not in text:
            return False
    if "not_contains" in condition:
        if str(condition["not_contains"]).lower() in text:
            return False
    if "field_equals" in condition:
        spec = condition["field_equals"] or {}
        for field, expected in spec.items():
            if str(payload.get(field, "")).lower() != str(expected).lower():
                return False
    return True


async def run_recipes(db: DatabaseManager, project_id: str, trigger: str,
                      payload: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate every active recipe for a trigger. Never raises."""
    if trigger not in RECIPE_TRIGGERS:
        return {"fired": 0}

    with db.get_session() as s:
        candidates = [_recipe_dict(r) for r in s.query(Recipe)
                      .filter(Recipe.project_id == project_id,
                              Recipe.trigger == trigger, Recipe.active == 1).all()]

    fired, results = 0, []
    for recipe in candidates:
        if not matches_condition(recipe["condition"], payload):
            continue

        outcome = {"recipe": recipe["name"], "action": recipe["action"], "ok": True}
        try:
            params = recipe["action_params"]
            if recipe["action"] == "webhook":
                await fire(db, project_id, trigger, payload)
            elif recipe["action"] == "create_idea":
                from src.services import idea_service

                template = params.get("text", "{summary}")
                text = template.format(**{k: str(v) for k, v in payload.items()}) \
                    if "{" in template else template
                idea_service.capture(db, project_id, text[:4000])
            elif recipe["action"] == "tag":
                from src.services import document_service as docs

                node_id = payload.get("node_id")
                if node_id and params.get("name"):
                    docs.add_tag(db, project_id, node_id, params["name"])
            elif recipe["action"] == "set_status":
                from src.services import document_service as docs

                node_id = payload.get("node_id")
                if node_id and params.get("status"):
                    docs.set_status(db, node_id, params["status"])
            elif recipe["action"] == "notify":
                outcome["message"] = params.get("message", "Recipe fired.")
        except Exception as e:
            outcome["ok"] = False
            outcome["error"] = str(e)[:300]

        fired += 1
        results.append(outcome)

        with db.get_session() as s:
            row = s.get(Recipe, recipe["id"])
            if row:
                row.run_count = (row.run_count or 0) + 1
                row.last_run_at = datetime.utcnow()
                s.commit()

    return {"fired": fired, "results": results, "evaluated": len(candidates)}
