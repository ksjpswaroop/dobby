"""
Time actually spent (Pending · Goals, Time & scheduling).

The planner could lay out a day and then had no idea what happened during it.
A 7-point item got a 150-minute block, and tomorrow it got another one — same
estimate, no memory, work never visibly shrinking. Every other goal in that
theme (remaining effort, completion projection, learned estimates, overrun
rescheduling) needs this table to exist first.

**Entries are append-only and immutable once stopped.** Editing history is
how a time log becomes fiction; a wrong entry is deleted, not rewritten.

**A running timer is an entry with no `ended_at`.** That means the
"am I tracking something?" question is a query rather than separate state
that can disagree with the log — the same derive-don't-store rule the board's
blocked column and the work graph both follow.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text,
)

from src.db.schema import Base

# How the entry got here. A timer is trustworthy; a manual entry is someone's
# recollection; a block entry is what the schedule claimed. Worth telling
# apart when these numbers later train the estimate model.
TIME_SOURCES = ("timer", "manual", "block")


class TimeEntry(Base):
    """One stretch of time spent on one work item."""

    __tablename__ = "time_entries"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    # Nullable so time can be logged against a project without a specific
    # feature — meetings and admin are real time even when untracked work.
    feature_id = Column(String, index=True)
    started_at = Column(DateTime, nullable=False, index=True)
    # NULL means still running. There is at most one of these per project.
    ended_at = Column(DateTime, index=True)
    # Denormalised on stop so totals never have to recompute from timestamps,
    # and so a manual entry can state a duration without inventing a range.
    minutes = Column(Integer, default=0)
    source = Column(String, nullable=False, default="timer")
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_time_project_started", "project_id", "started_at"),
        Index("idx_time_feature_started", "feature_id", "started_at"),
    )

    def __repr__(self):
        state = "running" if self.ended_at is None else f"{self.minutes}m"
        return f"<TimeEntry(feature='{self.feature_id}', {state})>"
