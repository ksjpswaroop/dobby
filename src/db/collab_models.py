"""
Collaboration & sharing (100-Day Roadmap, Phase 7: Days 61-70).

This is where Dobby stops being strictly single-user, so the security posture
matters more here than anywhere else in the app.

**Members are local records, not cloud accounts.** A `Member` is someone the
owner has invited to *this install*: the server runs on the owner's machine
(or wherever they host it) and authenticates members with scrypt-hashed
passwords. There is no Dobby account system, no central directory, and no
telemetry — inviting someone creates a row here and nothing else.

**Share links are capability URLs and are treated as such.** The token is
stored hashed, exactly like an API key, so a leaked database does not hand out
working links. Every link is read-only by construction — there is no code path
from a share token to a write — and can carry an expiry and a revocation.

`Presence` is deliberately ephemeral: a heartbeat row with a timestamp, swept
on read. Co-editing here means "you can see who else is in this document",
not operational-transform merging, which would be a dishonest thing to claim.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)

from src.db.schema import Base

# Roles are ordered by capability; `_rank` in the service relies on this order.
ROLES = ("viewer", "commenter", "editor", "admin", "owner")

ROLE_CAPABILITIES = {
    "viewer": {"read"},
    "commenter": {"read", "comment"},
    "editor": {"read", "comment", "write"},
    "admin": {"read", "comment", "write", "manage_members", "share"},
    "owner": {"read", "comment", "write", "manage_members", "share", "delete_project"},
}

REVIEW_STATES = ("open", "approved", "changes_requested", "cancelled")

MENTION_SOURCES = ("comment", "review", "document")


class Member(Base):
    """Someone invited to this install."""

    __tablename__ = "members"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    # scrypt hash as `salt$digest` (stdlib, memory-hard). Never plaintext,
    # and never recoverable.
    password_hash = Column(String, default="")
    # Set on invite, cleared on first sign-in. Hashed like everything else.
    invite_token_hash = Column(String, index=True)
    active = Column(Integer, default=1, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime)


class Membership(Base):
    """A member's role on one project."""

    __tablename__ = "memberships"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    member_id = Column(String, ForeignKey("members.id"), index=True, nullable=False)
    role = Column(String, nullable=False, default="viewer")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "member_id", name="uq_membership"),
    )


class MemberSession(Base):
    """A signed-in member's bearer token, stored hashed.

    Named MemberSession, not Session: `schema.Session` already exists for a
    project's generation session, and two mapped classes sharing a name make
    every string-based relationship in the registry ambiguous.
    """

    __tablename__ = "member_sessions"

    id = Column(String, primary_key=True)
    member_id = Column(String, ForeignKey("members.id"), index=True, nullable=False)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime)


class ShareLink(Base):
    """A read-only capability URL for a project or a single document."""

    __tablename__ = "share_links"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    # None = the whole project; set = exactly one document.
    node_id = Column(String, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    prefix = Column(String, nullable=False)
    label = Column(String, default="")
    expires_at = Column(DateTime, index=True)
    revoked_at = Column(DateTime)
    view_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_viewed_at = Column(DateTime)


class ReviewRequest(Base):
    """A request for someone to review a document (D65)."""

    __tablename__ = "review_requests"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    node_id = Column(String, index=True, nullable=False)
    requested_by = Column(String)          # member id, or "" for the local owner
    reviewer_id = Column(String, index=True)
    state = Column(String, default="open", index=True)
    note = Column(Text, default="")
    response = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime)


class Mention(Base):
    """An @mention of a member, and whether they have seen it (D70)."""

    __tablename__ = "mentions"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    member_id = Column(String, index=True, nullable=False)
    source = Column(String, nullable=False)
    source_id = Column(String)
    node_id = Column(String, index=True)
    text = Column(Text, default="")
    read_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_mentions_member_read", "member_id", "read_at"),)


class Presence(Base):
    """Ephemeral heartbeat: who is looking at what, right now."""

    __tablename__ = "presence"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    node_id = Column(String, index=True)
    member_id = Column(String, index=True)
    display_name = Column(String, default="")
    last_beat_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("member_id", "node_id", name="uq_presence_target"),
    )
