"""
Activity Timeline (100-Day Roadmap, Day 7).

Every other event-tracking mechanism in this codebase is purpose-built: runs
have `Tracer`/`RunEvent`, research has its own status machine. Rather than
wiring a generic emit-on-every-write audit call into each of those services
(broad, cross-cutting, and risky to bolt onto code that already works), this
derives a unified feed from the timestamped rows those services already
write — the same "read the existing state, don't touch the writers" approach
`run_todo.py` uses for the per-run checklist.

Pagination is cursor-based on (timestamp, id) but computed in Python after a
bounded per-table fetch: this is a local, single-user database, and a real
UNION-based cursor query across four unrelated tables would trade real
complexity for pagination correctness at a scale this app doesn't have.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.db.idea_models import Idea
from src.db.research_models import ResearchBrief
from src.db.run_models import Run
from src.db.schema import DatabaseManager, FeatureBacklog

FETCH_PER_SOURCE = 200


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _idea_events(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with db.get_session() as s:
        rows = (s.query(Idea).filter(Idea.project_id == project_id)
                 .order_by(Idea.created_at.desc()).limit(FETCH_PER_SOURCE).all())
        for i in rows:
            events.append({
                "id": f"idea_captured:{i.id}", "type": "idea_captured", "category": "idea",
                "title": f"Captured an idea: “{i.text[:80]}”",
                "timestamp": _iso(i.created_at), "route": "/ideas",
            })
            if i.status == "backlog" and i.promoted_feature_id:
                events.append({
                    "id": f"idea_triaged:{i.id}", "type": "idea_triaged_backlog", "category": "idea",
                    "title": f"Triaged idea to backlog: “{i.text[:80]}”",
                    "timestamp": _iso(i.updated_at), "route": "/backlog",
                })
            elif i.status == "research" and i.promoted_brief_id:
                events.append({
                    "id": f"idea_triaged:{i.id}", "type": "idea_triaged_research", "category": "idea",
                    "title": f"Triaged idea to research: “{i.text[:80]}”",
                    "timestamp": _iso(i.updated_at), "route": "/research",
                })
            elif i.status == "archived":
                events.append({
                    "id": f"idea_triaged:{i.id}", "type": "idea_archived", "category": "idea",
                    "title": f"Archived an idea: “{i.text[:80]}”",
                    "timestamp": _iso(i.updated_at), "route": "/ideas",
                })
    return events


def _feature_events(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with db.get_session() as s:
        rows = (s.query(FeatureBacklog).filter(FeatureBacklog.project_id == project_id)
                 .order_by(FeatureBacklog.created_at.desc()).limit(FETCH_PER_SOURCE).all())
        for f in rows:
            events.append({
                "id": f"feature_added:{f.id}", "type": "feature_added", "category": "feature",
                "title": f"Added to backlog: {f.title}",
                "timestamp": _iso(f.created_at), "route": "/backlog",
            })
            if f.status == "completed" and f.completed_at:
                events.append({
                    "id": f"feature_completed:{f.id}", "type": "feature_completed", "category": "feature",
                    "title": f"Completed: {f.title}",
                    "timestamp": _iso(f.completed_at), "route": "/backlog",
                })
    return events


def _run_events(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with db.get_session() as s:
        rows = (s.query(Run).filter(Run.project_id == project_id)
                 .order_by(Run.started_at.desc()).limit(FETCH_PER_SOURCE).all())
        for r in rows:
            events.append({
                "id": f"run_started:{r.id}", "type": f"run_started_{r.kind}", "category": "run",
                "title": f"Started {r.kind}: {r.label}",
                "timestamp": _iso(r.started_at), "route": "/logs",
            })
            if r.status != "running" and r.finished_at:
                events.append({
                    "id": f"run_finished:{r.id}", "type": f"run_{r.status}", "category": "run",
                    "title": f"{'Verified' if r.kind == 'verify' else 'Finished'} {r.kind}: {r.label} ({r.status})",
                    "timestamp": _iso(r.finished_at), "route": "/logs",
                })
    return events


def _research_events(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with db.get_session() as s:
        rows = (s.query(ResearchBrief).filter(ResearchBrief.project_id == project_id)
                 .order_by(ResearchBrief.created_at.desc()).limit(FETCH_PER_SOURCE).all())
        for b in rows:
            events.append({
                "id": f"research_started:{b.id}", "type": "research_started", "category": "research",
                "title": f"Started research: {b.topic[:80]}",
                "timestamp": _iso(b.created_at), "route": "/research",
            })
            if b.status in ("complete", "failed"):
                events.append({
                    "id": f"research_finished:{b.id}",
                    "type": "research_complete" if b.status == "complete" else "research_failed",
                    "category": "research",
                    "title": f"Research {b.status}: {b.topic[:80]}",
                    "timestamp": _iso(b.updated_at), "route": "/research",
                })
    return events


CATEGORIES = ("idea", "feature", "run", "research")


def list_events(db: DatabaseManager, project_id: str, category: Optional[str] = None,
                cursor: Optional[str] = None, limit: int = 30) -> Dict[str, Any]:
    events = (
        _idea_events(db, project_id) + _feature_events(db, project_id)
        + _run_events(db, project_id) + _research_events(db, project_id)
    )
    events = [e for e in events if e["timestamp"]]
    if category:
        events = [e for e in events if e["category"] == category]

    # Newest first; tie-break on id so identical timestamps stay in a stable order.
    events.sort(key=lambda e: (e["timestamp"], e["id"]), reverse=True)

    if cursor:
        try:
            ts, cid = cursor.rsplit("|", 1)
        except ValueError:
            ts, cid = cursor, ""
        events = [e for e in events if (e["timestamp"], e["id"]) < (ts, cid)]

    page = events[:limit]
    next_cursor = f"{page[-1]['timestamp']}|{page[-1]['id']}" if len(page) == limit else None
    return {"events": page, "next_cursor": next_cursor}
