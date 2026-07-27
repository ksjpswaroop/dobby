"""
Today Home (100-Day Roadmap, Day 1).

One endpoint assembling today's actionable slice, so the landing screen is a
single round-trip rather than the five the Dashboard would otherwise make.
Every section is capped — a home screen that grows with the database stops
being a home screen.

The sections are deliberately the things that are *waiting on the builder*:
asks needing a decision, ideas needing triage, sessions left mid-flight, runs
that failed. Top-Pareto backlog is the one forward-looking section, for when
nothing is blocked.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from src.db.idea_models import Idea
from src.db.inbox_models import Ask
from src.db.run_models import Run
from src.db.schema import DatabaseManager, FeatureBacklog
from src.db.session_models import WorkSession

SECTION_LIMIT = 5


def _greeting(now: datetime) -> str:
    h = now.hour
    if h < 12:
        return "Good morning"
    if h < 18:
        return "Good afternoon"
    return "Good evening"


def build_home(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        asks = (s.query(Ask)
                .filter(Ask.project_id == project_id, Ask.state == "pending")
                .order_by(Ask.created_at.desc()).limit(SECTION_LIMIT).all())
        needs_decision = [
            {"id": a.id, "title": a.title, "risk": a.risk, "route": "/inbox"}
            for a in asks
        ]

        ideas = (s.query(Idea)
                 .filter(Idea.project_id == project_id, Idea.status == "inbox")
                 .order_by(Idea.created_at.desc()).limit(SECTION_LIMIT).all())
        needs_triage = [
            {"id": i.id, "title": i.text[:120], "route": "/ideas"} for i in ideas
        ]

        sessions = (s.query(WorkSession)
                    .filter(WorkSession.project_id == project_id,
                            WorkSession.state.in_(("active", "suspended")))
                    .order_by(WorkSession.last_active_at.desc())
                    .limit(SECTION_LIMIT).all())
        in_progress = [
            {"id": w.id, "title": w.title or "Untitled session", "state": w.state,
             "route": "/logs"}
            for w in sessions
        ]

        failed = (s.query(Run)
                  .filter(Run.project_id == project_id, Run.status == "failed")
                  .order_by(Run.started_at.desc()).limit(SECTION_LIMIT).all())
        needs_attention = [
            {"id": r.id, "title": r.label, "kind": r.kind, "route": "/logs"}
            for r in failed
        ]

        top = (s.query(FeatureBacklog)
               .filter(FeatureBacklog.project_id == project_id,
                       FeatureBacklog.status == "backlog")
               .order_by(FeatureBacklog.pareto_score.desc())
               .limit(SECTION_LIMIT).all())
        top_backlog = [
            {"id": f.id, "title": f.title, "pareto_score": round(f.pareto_score or 0, 2),
             "route": "/backlog"}
            for f in top
        ]

    total = (len(needs_decision) + len(needs_triage) + len(in_progress) + len(needs_attention))
    return {
        "greeting": _greeting(datetime.now()),
        "needs_decision": needs_decision,
        "needs_triage": needs_triage,
        "in_progress": in_progress,
        "needs_attention": needs_attention,
        "top_backlog": top_backlog,
        "clear": total == 0,
    }
