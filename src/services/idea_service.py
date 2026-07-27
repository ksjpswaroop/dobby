"""
Idea capture and triage (100-Day Roadmap, Days 2-3).

`capture()` is the only function that needs to be fast — everything else
(triage into Backlog or Research, archive) can happen later, at a desk, with
more attention than the moment the idea was had.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.db.idea_models import STATUSES, Idea
from src.db.schema import DatabaseManager, FeatureBacklog, Project


class IdeaError(Exception):
    pass


def _idea_dict(idea: Idea) -> Dict[str, Any]:
    return {
        "id": idea.id,
        "project_id": idea.project_id,
        "text": idea.text,
        "status": idea.status,
        "promoted_feature_id": idea.promoted_feature_id,
        "promoted_brief_id": idea.promoted_brief_id,
        "pinned": bool(idea.pinned),
        "created_at": idea.created_at.isoformat() if idea.created_at else None,
        "updated_at": idea.updated_at.isoformat() if idea.updated_at else None,
    }


def capture(db: DatabaseManager, project_id: str, text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise IdeaError("An idea needs some text.")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise IdeaError("Project not found.")
        idea = Idea(id=str(uuid.uuid4()), project_id=project_id, text=text[:4000], status="inbox")
        s.add(idea)
        s.commit()
        return _idea_dict(idea)


def get(db: DatabaseManager, idea_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        return _idea_dict(idea) if idea else None


def list_ideas(db: DatabaseManager, project_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    if status and status not in STATUSES:
        raise IdeaError(f"Unknown status. One of: {', '.join(STATUSES)}")
    with db.get_session() as s:
        q = s.query(Idea).filter(Idea.project_id == project_id)
        if status:
            q = q.filter(Idea.status == status)
        rows = q.order_by(Idea.pinned.desc(), Idea.created_at.desc()).all()
        return [_idea_dict(i) for i in rows]


def archive(db: DatabaseManager, idea_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        if not idea:
            raise IdeaError("Idea not found.")
        idea.status = "archived"
        idea.updated_at = datetime.utcnow()
        s.commit()
        return _idea_dict(idea)


def set_pinned(db: DatabaseManager, idea_id: str, pinned: bool) -> Dict[str, Any]:
    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        if not idea:
            raise IdeaError("Idea not found.")
        idea.pinned = "1" if pinned else ""
        idea.updated_at = datetime.utcnow()
        s.commit()
        return _idea_dict(idea)


def delete(db: DatabaseManager, idea_id: str) -> bool:
    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        if not idea:
            return False
        s.delete(idea)
        s.commit()
        return True


def triage_to_backlog(db: DatabaseManager, idea_id: str,
                       impact_score: int = 5, effort_score: int = 5,
                       risk_score: int = 5) -> Dict[str, Any]:
    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        if not idea:
            raise IdeaError("Idea not found.")
        feature_id = str(uuid.uuid4())
        pareto_score = (impact_score * 0.6) - (effort_score * 0.3) - (risk_score * 0.1)
        s.add(FeatureBacklog(
            id=feature_id, project_id=idea.project_id,
            title=idea.text[:200], description=idea.text,
            category="idea", impact_score=impact_score, effort_score=effort_score,
            risk_score=risk_score, pareto_score=pareto_score, status="backlog",
        ))
        idea.status = "backlog"
        idea.promoted_feature_id = feature_id
        idea.updated_at = datetime.utcnow()
        s.commit()
        return _idea_dict(idea)


def triage_to_research(db: DatabaseManager, idea_id: str) -> Dict[str, Any]:
    from src.services.research_service import create_brief

    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        if not idea:
            raise IdeaError("Idea not found.")
        project_id, text = idea.project_id, idea.text

    brief = create_brief(db, project_id, topic=text[:500], context=text)

    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        idea.status = "research"
        idea.promoted_brief_id = brief["id"]
        idea.updated_at = datetime.utcnow()
        s.commit()
        return _idea_dict(idea)
