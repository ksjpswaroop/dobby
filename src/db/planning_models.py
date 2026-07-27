"""
Planning & project management (100-Day Roadmap, Phase 5: Days 41-50).

`PlanningMeta` is the pattern that keeps this whole phase additive: rather
than bolting sprint, board-column, and estimate columns onto `FeatureBacklog`
— a table the generation pipeline writes on every run — planning state lives
in its own row keyed by feature id. A feature with no row is simply an
unplanned backlog item, which is exactly how the app behaved before.

`FeatureStatusChange` is append-only and is what makes Delivery Analytics
(D50) possible at all: velocity, throughput, and cycle time are all questions
about *when* something moved, and that is unanswerable from current state.

`Blocker` deliberately stores a directed pair rather than a list column, so
"what is blocking X" and "what does X block" are both single indexed queries,
and a cycle can be detected before it is written.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)

from src.db.schema import Base

BOARD_COLUMNS = ("backlog", "todo", "in_progress", "blocked", "done")

# How a legacy FeatureBacklog.status maps onto a board column when a feature
# has never been placed on the board.
STATUS_TO_COLUMN = {
    "backlog": "backlog",
    "in_progress": "in_progress",
    "completed": "done",
    "skipped": "done",
}

SPRINT_STATES = ("planned", "active", "closed")
ESTIMATE_UNITS = ("points", "hours")


class PlanningMeta(Base):
    """Planning state for one backlog feature."""

    __tablename__ = "planning_meta"

    feature_id = Column(String, ForeignKey("feature_backlog.id"), primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    board_column = Column(String, index=True)
    sprint_id = Column(String, ForeignKey("sprints.id"), index=True)
    milestone_id = Column(String, ForeignKey("milestones.id"), index=True)
    # Seeded from the Pareto effort score, then refined by the user.
    estimate = Column(Float)
    estimate_unit = Column(String, default="points")
    order_index = Column(Integer, default=0)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_planning_project_column", "project_id", "board_column"),)


class FeatureStatusChange(Base):
    """Append-only record of a feature moving between board columns."""

    __tablename__ = "feature_status_changes"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    feature_id = Column(String, index=True, nullable=False)
    from_column = Column(String)
    to_column = Column(String, nullable=False)
    sprint_id = Column(String, index=True)
    estimate = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_changes_project_created", "project_id", "created_at"),)


class Sprint(Base):
    __tablename__ = "sprints"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    goal = Column(Text, default="")
    starts_on = Column(DateTime, nullable=False)
    ends_on = Column(DateTime, nullable=False)
    state = Column(String, default="planned", index=True)
    # Capacity for the window, in the same unit as the estimates.
    capacity = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)


class Milestone(Base):
    __tablename__ = "milestones"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    due_on = Column(DateTime, index=True)
    reached_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class Blocker(Base):
    """`feature_id` is blocked by `blocked_by_id`."""

    __tablename__ = "blockers"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    feature_id = Column(String, index=True, nullable=False)
    blocked_by_id = Column(String, index=True, nullable=False)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("feature_id", "blocked_by_id", name="uq_blocker_pair"),
    )


class Objective(Base):
    """An OKR objective (D49)."""

    __tablename__ = "objectives"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    period = Column(String, default="")  # free text, e.g. "2026 Q3"
    created_at = Column(DateTime, default=datetime.utcnow)


class KeyResult(Base):
    __tablename__ = "key_results"

    id = Column(String, primary_key=True)
    objective_id = Column(String, ForeignKey("objectives.id"), index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    # Features linked to this KR; progress is computed from their completion,
    # weighted by Pareto impact so finishing a big thing moves it more.
    target = Column(Float, default=100.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class KeyResultLink(Base):
    __tablename__ = "key_result_links"

    id = Column(String, primary_key=True)
    key_result_id = Column(String, ForeignKey("key_results.id"), index=True, nullable=False)
    feature_id = Column(String, index=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("key_result_id", "feature_id", name="uq_kr_feature"),
    )


class DailyPlan(Base):
    """A day's committed list (D47). One per project per local date."""

    __tablename__ = "daily_plans"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    plan_date = Column(String, nullable=False, index=True)  # ISO local date
    # [{feature_id, title, estimate, done}] — denormalised so the plan is a
    # record of what you committed to, even if the feature is later renamed.
    items = Column(JSON, default=list)
    committed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "plan_date", name="uq_daily_plan"),
    )
