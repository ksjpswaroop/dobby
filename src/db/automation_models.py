"""
Automation models — scheduled work that runs without you being there.

An **Automation** is a saved task with a schedule. Each firing produces an
**AutomationRun**, which links to the ordinary `Run` row so a scheduled job
appears in Logs & Traces exactly like an interactive one — there is no separate
place to look for "what did the robot do".

Reverse-engineered from OpenWorker's scheduling model (see the
`OW · Features` tab of the roadmap): cron plus one-shot, catch-up on startup,
skip-on-overlap, a max-runs cap, and unread tracking so a completed run can
demand attention.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
)

from src.db.schema import Base

# What an automation does when it fires.
ACTION_KINDS = ("research", "generate", "verify", "digest")

TRIGGER_KINDS = ("cron", "once")


class Automation(Base):
    """A task with a schedule."""

    __tablename__ = "automations"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, default="")

    action = Column(String, nullable=False)              # one of ACTION_KINDS
    action_config = Column(JSON, default=dict)           # e.g. {"topic": "..."}

    trigger = Column(String, nullable=False, default="cron")  # cron | once
    cron = Column(String, default="")                    # when trigger == cron
    run_at = Column(DateTime)                            # when trigger == once
    timezone = Column(String, default="UTC")

    enabled = Column(Boolean, default=True, index=True)
    # Guard against a runaway schedule; 0 means no cap.
    max_runs = Column(Integer, default=0)
    run_count = Column(Integer, default=0)

    # Set while a firing is in flight, so the loop can skip rather than stack up.
    is_running = Column(Boolean, default=False)

    next_run = Column(DateTime, index=True)
    last_run = Column(DateTime)
    last_status = Column(String)                          # ok | failed | skipped
    last_error = Column(Text)

    # Cleared when the user opens the run. Drives the "needs attention" badge.
    unread_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_automations_due", "enabled", "next_run"),)

    def __repr__(self):
        return f"<Automation(name='{self.name}', next={self.next_run})>"


class AutomationRun(Base):
    """One firing of an automation."""

    __tablename__ = "automation_runs"

    id = Column(String, primary_key=True)
    automation_id = Column(String, ForeignKey("automations.id"), index=True,
                           nullable=False)
    # The Logs & Traces row for this firing, when one was created.
    run_id = Column(String, index=True)
    status = Column(String, nullable=False, default="running")  # running|ok|failed|skipped
    trigger_source = Column(String, default="schedule")   # schedule | manual | catchup
    summary = Column(Text, default="")
    error = Column(Text)
    read = Column(Boolean, default=False)
    duration_ms = Column(Integer)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)

    __table_args__ = (Index("idx_autoruns_started", "automation_id", "started_at"),)
