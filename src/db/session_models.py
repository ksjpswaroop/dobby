"""
Durable work sessions and permission modes (OW 20-24 — Next Task 7).

Dobby has a `Session` table already, but it holds wizard state: a single
pipeline's progress, not a unit of work you can walk away from and come back
to. This adds the thing the roadmap actually asks for — a session that survives
a restart, carries its own permission posture, and can be suspended and resumed.

**Permission mode is the load-bearing idea.** The approval gate already asks
before anything consequential, but "ask every time" is only correct when
someone is watching. A scheduled job at 3am needs a posture decided in advance:

    ask         — the default. Every gated action raises an Inbox item.
    unattended  — low-risk actions proceed; medium and high still ask, and
                  the decision is recorded either way.
    readonly    — nothing that writes, sends, or executes is permitted at all,
                  regardless of grants. The strictest setting wins.

`readonly` deliberately overrides standing grants. A mode that a grant could
quietly defeat would be a setting that lies to the user.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
)

from src.db.schema import Base

PERMISSION_MODES = ("ask", "unattended", "readonly")

SESSION_STATES = ("active", "suspended", "completed", "failed")

# Risk levels an unattended session will allow through without asking.
UNATTENDED_AUTO_RISK = ("low",)


class WorkSession(Base):
    """A unit of work that outlives the process that started it."""

    __tablename__ = "work_sessions"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    kind = Column(String, default="general")   # general | research | generation | automation

    permission_mode = Column(String, nullable=False, default="ask")
    state = Column(String, nullable=False, default="active", index=True)

    # Arbitrary caller state, checkpointed so a resumed session picks up where
    # it left off rather than starting over.
    checkpoint = Column(JSON, default=dict)
    # Monotonic counter — lets a resumed caller detect it has stale state.
    revision = Column(Integer, default=0)

    # Roots this session may touch (OW 23). Empty means the project workspace.
    workspace_roots = Column(JSON, default=list)

    model = Column(String)
    note = Column(Text, default="")
    error = Column(Text)

    # Set when suspended so a resume can report how long it slept.
    suspended_at = Column(DateTime)
    resumed_at = Column(DateTime)
    last_active_at = Column(DateTime, default=datetime.utcnow, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_worksessions_project_state", "project_id", "state"),
    )

    def __repr__(self):
        return f"<WorkSession(title='{self.title}', mode={self.permission_mode})>"


class SessionEvent(Base):
    """An entry in a session's own timeline.

    Separate from `RunEvent`: a run is one execution, a session may span many
    of them plus suspensions, mode changes and approvals.
    """

    __tablename__ = "session_events"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("work_sessions.id"), index=True,
                        nullable=False)
    event = Column(String, nullable=False)     # started | suspended | resumed | …
    message = Column(Text, default="")
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
