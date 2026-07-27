"""
First-run onboarding (100-Day Roadmap, Day 10).

Every step's completion is *derived* from real data — an idea row exists, a
node exists — rather than tracked in a parallel checklist table. A stored
checklist can drift from reality (mark a step done, delete the thing it was
about); a derived one cannot. The only persisted state is whether the builder
dismissed the tour.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.db.idea_models import Idea
from src.db.schema import DatabaseManager, Node


def _model_ready() -> bool:
    from src.settings import get_settings

    settings = get_settings()
    return bool(getattr(settings, "model", "") and getattr(settings, "ollama_host", ""))


def build_checklist(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    from src.settings import get_settings

    with db.get_session() as s:
        captured = s.query(Idea).filter(Idea.project_id == project_id).first() is not None
        triaged = (s.query(Idea)
                   .filter(Idea.project_id == project_id,
                           Idea.status.in_(("backlog", "research")))
                   .first() is not None)
        generated = (s.query(Node)
                     .filter(Node.project_id == project_id)
                     .first() is not None)

    steps: List[Dict[str, Any]] = [
        {"id": "model", "label": "Connect a local model",
         "detail": "Dobby runs on Ollama — nothing leaves your machine.",
         "route": "/settings", "done": _model_ready()},
        {"id": "capture", "label": "Capture your first idea",
         "detail": "Press ⌘I from anywhere, or use the Ideas page.",
         "route": "/ideas", "done": captured},
        {"id": "triage", "label": "Triage it into the backlog",
         "detail": "Turn a raw thought into a Pareto-scored feature.",
         "route": "/ideas", "done": triaged},
        {"id": "generate", "label": "Generate your first document",
         "detail": "Wizard walks you through it; YOLO does it in one pass.",
         "route": "/wizard", "done": generated},
    ]

    done_count = sum(1 for s_ in steps if s_["done"])
    return {
        "steps": steps,
        "done_count": done_count,
        "total": len(steps),
        "complete": done_count == len(steps),
        "dismissed": bool(getattr(get_settings(), "onboarding_dismissed", False)),
    }


def set_dismissed(dismissed: bool) -> Dict[str, Any]:
    from src.settings.store import get_settings_store

    get_settings_store().update(onboarding_dismissed=dismissed)
    return {"dismissed": dismissed}
