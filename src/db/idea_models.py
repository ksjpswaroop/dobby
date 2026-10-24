"""
Idea capture (100-Day Roadmap, Days 2-3: Quick-Capture + Idea Inbox).

The gap this closes: every existing entry point into Dobby — Wizard, YOLO,
Research — wants something already shaped (a feature, a topic). There was
nowhere to put a raw, half-formed thought in the three seconds you have it,
which is exactly the moment a "daily driver" tool has to win or lose. An Idea
is deliberately the lowest-friction object in the schema: one required field
(`text`), nothing else, captured now and shaped later.

Triage promotes an idea into something the rest of the app already knows how
to do something with — a `FeatureBacklog` row (Pareto-scored, same as any
other feature) or a `ResearchBrief` (created but not auto-run, matching the
propose-don't-act pattern the Research and Inbox stages already use). The
idea itself is never deleted on promotion, only marked — so "what did I
capture, and what became of it" stays answerable.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text

from src.db.schema import Base

STATUSES = ("inbox", "backlog", "research", "archived")


class Idea(Base):
    """One raw captured thought."""

    __tablename__ = "ideas"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="inbox", index=True)

    # Set once triaged, so "what became of this" is always answerable without
    # deleting the original capture.
    promoted_feature_id = Column(String)
    promoted_brief_id = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_ideas_project_status", "project_id", "status"),)

    def __repr__(self):
        return f"<Idea(id='{self.id}', status='{self.status}')>"
