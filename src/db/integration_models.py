"""
Outbound webhooks, API keys, and automation recipes
(100-Day Roadmap, Phase 6: D58, D59, D60).

These three are the local-first half of the integrations phase: a webhook
fires *outward* from this machine, the "public" API is this machine's own
server with real authentication in front of it, and a recipe is local
automation. None of them need hosting.

`ApiKey` stores only a SHA-256 hash. The plaintext key is returned exactly
once, at creation, and is unrecoverable afterwards — so a leaked database
does not hand over working credentials. That is the same reason the launch
token is never written anywhere readable.

`WebhookDelivery` records every attempt including failures, because a webhook
that silently stops firing is worse than one that visibly errors.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
)

from src.db.schema import Base

# Events a webhook can subscribe to. Explicit rather than free-form so a typo
# produces an error at subscribe time instead of a webhook that never fires.
WEBHOOK_EVENTS = (
    "idea.captured", "idea.triaged", "document.created", "document.approved",
    "feature.completed", "run.failed", "run.completed", "research.completed",
)

# Scopes an API key can hold. read is deliberately separate from write: most
# integrations only need to read.
API_SCOPES = ("read", "write", "admin")

RECIPE_TRIGGERS = ("idea.captured", "document.approved", "feature.completed",
                   "run.failed", "schedule")

RECIPE_ACTIONS = ("webhook", "tag", "create_idea", "set_status", "notify")


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    url = Column(String, nullable=False)
    events = Column(JSON, default=list)
    # Shared secret used to HMAC-sign each delivery, so the receiver can
    # verify the request really came from this Dobby install.
    secret = Column(String, default="")
    active = Column(Integer, default=1, index=True)
    description = Column(String, default="")
    failure_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_fired_at = Column(DateTime)


class WebhookDelivery(Base):
    """Every attempt, including failures — a silently dead webhook is worse."""

    __tablename__ = "webhook_deliveries"

    id = Column(String, primary_key=True)
    webhook_id = Column(String, ForeignKey("webhooks.id"), index=True, nullable=False)
    event = Column(String, nullable=False, index=True)
    payload = Column(JSON, default=dict)
    status_code = Column(Integer)
    ok = Column(Integer, default=0)
    error = Column(Text)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_deliveries_hook_created", "webhook_id", "created_at"),)


class ApiKey(Base):
    """A hashed API key. The plaintext exists only in the creation response."""

    __tablename__ = "api_keys"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    # First 8 chars, so the UI can show *which* key without holding the key.
    prefix = Column(String, nullable=False)
    scopes = Column(JSON, default=list)
    project_id = Column(String, index=True)  # None = all projects
    active = Column(Integer, default=1, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)
    use_count = Column(Integer, default=0)


class Recipe(Base):
    """A when-this-then-that rule, evaluated locally (D60)."""

    __tablename__ = "recipes"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    trigger = Column(String, nullable=False, index=True)
    # Optional filter, e.g. {"contains": "bug"} — a recipe that fires on every
    # capture is usually not what someone wanted.
    condition = Column(JSON, default=dict)
    action = Column(String, nullable=False)
    action_params = Column(JSON, default=dict)
    active = Column(Integer, default=1, index=True)
    run_count = Column(Integer, default=0)
    last_run_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
