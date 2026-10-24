"""
Decisions as first-class work (Work Graph, step 1).

Nothing in Dobby captured the shape of "RAG vs. Structured Reasoning for
Verity — decide by Aug 3". That is not an idea (it is already framed), not a
backlog feature (nobody builds a decision), and not a document (it is
unresolved). It is a *fork* that work is waiting behind, and it is usually
the real blocker on a project long before any code is.

Three consequences shape this model:

**A decision has options.** A "decision" with no alternatives is just a task.
Storing options explicitly is what lets the app show the fork, record which
branch was taken, and keep the rejected ones — because "why didn't we do the
other thing" is the question people actually come back for.

**A decision can block work.** `DecisionLink` gives it edges to features and
documents, so an open decision removes blocked work from the ready set
exactly like an unfinished `Blocker` does. This is what makes "the current
decision is the main blocker for this project" a computed fact.

**Deciding is append-only.** The chosen option, the rationale, and the
timestamp are written once and the status moves to `decided`. Changing your
mind creates a *superseding* decision rather than editing history, so the
record of what you believed in July survives you disagreeing with it in
September.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)

from src.db.schema import Base

# open      — the fork is live and may be blocking work
# decided   — a branch was taken; rationale recorded
# superseded— a later decision replaced this one
DECISION_STATES = ("open", "decided", "superseded")

# What a decision can be attached to.
LINK_TYPES = ("feature", "document", "objective")


class Decision(Base):
    """One unresolved (or resolved) fork in the work."""

    __tablename__ = "decisions"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    question = Column(Text, default="")
    status = Column(String, nullable=False, default="open", index=True)

    # The date by which staying undecided starts costing something. Nullable:
    # plenty of real decisions have no deadline, and inventing one would make
    # the overdue signal meaningless.
    due_on = Column(DateTime, index=True)

    chosen_option_id = Column(String)
    rationale = Column(Text, default="")
    decided_at = Column(DateTime)

    # Set when a later decision replaces this one, so the chain is walkable.
    superseded_by = Column(String, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_decisions_project_status", "project_id", "status"),
        Index("idx_decisions_status_due", "status", "due_on"),
    )

    def __repr__(self):
        return f"<Decision(id='{self.id}', status='{self.status}', title='{self.title[:30]}')>"


class DecisionOption(Base):
    """One branch of a decision. Rejected options are kept, never deleted."""

    __tablename__ = "decision_options"

    id = Column(String, primary_key=True)
    decision_id = Column(String, ForeignKey("decisions.id"), index=True, nullable=False)
    label = Column(String, nullable=False)
    note = Column(Text, default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_options_decision_order", "decision_id", "sort_order"),)


class DecisionLink(Base):
    """An edge from a decision to work that is waiting on it."""

    __tablename__ = "decision_links"

    id = Column(String, primary_key=True)
    decision_id = Column(String, ForeignKey("decisions.id"), index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False, index=True)
    # True when the linked work genuinely cannot proceed until this is decided,
    # as opposed to merely being related to it.
    blocking = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("decision_id", "entity_type", "entity_id",
                         name="uq_decision_link"),
    )
