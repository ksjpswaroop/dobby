"""
Approvals & Inbox (OW rows 8, 9, 13-17, 19).

The problem this solves: Dobby now does work unattended. Automations fire on a
schedule, research reaches out to the network, and the roadmap adds a terminal
and outbound messaging. Something has to stand between "the agent decided to do
X" and "X happened", and that something has to work when nobody is looking at
the screen.

Three pieces:

* **Ask** — a parked question or approval request. It survives restarts, can be
  answered from anywhere, and carries enough context to decide without
  re-reading the conversation that produced it.
* **Grant** — a standing scoped approval. "Yes, and stop asking me about this
  kind of thing for this target." Without it, approval fatigue makes people
  approve everything reflexively, which is worse than not asking.
* **Decision** — the recorded answer, so an audit can show who allowed what.

An Ask is *parked*, not blocking: the caller may wait on it, but the record
lives in the database and resolving it later works exactly the same. That is
what makes it resolvable "from anywhere" rather than only from the tab that
raised it.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
)

from src.db.schema import Base

# What is being asked for. `risk` drives how loudly the UI presents it.
ASK_KINDS = ("approval", "question", "choice")

# Categories of guarded action. A grant is scoped to one of these plus a target.
CAPABILITIES = (
    "shell.execute",      # run a command
    "net.fetch",          # reach a host
    "message.send",       # send on the user's behalf
    "file.write",         # write outside the project
    "automation.run",     # fire a scheduled task that does any of the above
)

RISK_LEVELS = ("low", "medium", "high")

ASK_STATES = ("pending", "approved", "denied", "expired", "cancelled")


class Ask(Base):
    """A parked request for a human decision."""

    __tablename__ = "asks"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)

    kind = Column(String, nullable=False, default="approval")
    capability = Column(String, index=True)        # one of CAPABILITIES
    # What the action operates on: a host, a command, a channel. Grants match
    # on this, so it has to be stable and comparable.
    target = Column(String, default="")

    title = Column(String, nullable=False)
    detail = Column(Text, default="")
    risk = Column(String, default="medium")

    # For kind == "choice": the offered replies. Free text is always allowed
    # too, so a user is never boxed into options that miss the point.
    options = Column(JSON, default=list)

    state = Column(String, nullable=False, default="pending", index=True)
    answer = Column(Text, default="")
    answered_by = Column(String, default="")
    answered_at = Column(DateTime)

    # Where the ask came from, so the UI can link back.
    source = Column(String, default="")            # automation | research | manual
    source_id = Column(String, index=True)
    run_id = Column(String, index=True)

    # Asks that nobody answers must not pile up forever.
    expires_at = Column(DateTime, index=True)
    # Whether the requester is still waiting. A resumed session reconciles by
    # checking this against what it remembers.
    awaited = Column(Boolean, default=False)

    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_asks_project_state", "project_id", "state"),
        Index("idx_asks_pending", "state", "created_at"),
    )

    def __repr__(self):
        return f"<Ask({self.capability} {self.target!r} {self.state})>"


class Grant(Base):
    """A standing approval: capability + target, until revoked or expired.

    Scoped deliberately narrowly. A grant is not "trust this agent", it is
    "this capability, on this target, for this long" — which is the difference
    between a useful permission and a blank cheque.
    """

    __tablename__ = "grants"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    capability = Column(String, nullable=False, index=True)
    # Exact match, or a single leading "*" wildcard (e.g. "*.github.com").
    target = Column(String, nullable=False, default="")
    note = Column(Text, default="")

    granted_by = Column(String, default="user")
    # NULL means until revoked.
    expires_at = Column(DateTime, index=True)
    revoked_at = Column(DateTime)

    # How often this grant has short-circuited an ask — shown in the UI so a
    # forgotten broad grant is visible rather than invisible.
    use_count = Column(Integer, default=0)
    last_used_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_grants_lookup", "project_id", "capability", "target"),)

    def __repr__(self):
        return f"<Grant({self.capability} -> {self.target!r})>"
