"""
Search API — one query across everything local.

Covers projects, generated documents (nodes), backlog features, and runs. This
is **full-text** search (SQLite LIKE over titles and content), which is fast,
dependency-free, and enough at local scale. Semantic/embedding search is a
later upgrade; the response shape is designed so it can be swapped in without
changing the UI.
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Query

from src.db.run_models import Run
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1", tags=["Search"])

# Document node types worth surfacing (a feature's generated artifacts).
DOC_TYPES = (
    "feature", "user_story", "functional_analysis", "flowchart",
    "pseudocode", "tdd_tests", "documentation",
)


def get_db() -> DatabaseManager:
    from src.main import app

    return app.state.db


def _snippet(text: Optional[str], term: str, width: int = 140) -> str:
    """A short excerpt centred on the first match, so results show context."""
    if not text:
        return ""
    low, t = text.lower(), term.lower()
    i = low.find(t)
    if i < 0:
        return text[:width].strip()
    start = max(0, i - width // 3)
    end = min(len(text), start + width)
    out = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + out + ("…" if end < len(text) else "")


@router.get("/search")
async def search(
    q: str = Query("", description="Search term"),
    project_id: Optional[str] = None,
    limit: int = Query(30, ge=1, le=200),
    db: DatabaseManager = Depends(get_db),
) -> Dict[str, Any]:
    term = q.strip()
    if not term:
        return {"query": "", "count": 0, "results": []}

    like = f"%{term}%"
    results: List[Dict[str, Any]] = []

    with db.get_session() as s:
        # -- Projects ------------------------------------------------------
        for p in (
            s.query(Project)
            .filter(Project.name.ilike(like) | Project.idea.ilike(like))
            .limit(limit)
            .all()
        ):
            results.append({
                "type": "project",
                "id": p.id,
                "title": p.name,
                "subtitle": "Project",
                "snippet": _snippet(p.idea or p.description, term),
                "route": "/projects",
            })

        # -- Documents (generated nodes) -----------------------------------
        nq = s.query(Node).filter(
            Node.node_type.in_(DOC_TYPES),
            (Node.title.ilike(like) | Node.content.ilike(like)),
        )
        if project_id:
            nq = nq.filter(Node.project_id == project_id)
        for n in nq.limit(limit).all():
            results.append({
                "type": "document",
                "id": n.id,
                "title": n.title,
                "subtitle": (n.node_type or "").replace("_", " ").title(),
                "snippet": _snippet(n.content, term),
                "route": "/documents",
                "project_id": n.project_id,
            })

        # -- Backlog features ----------------------------------------------
        fq = s.query(FeatureBacklog).filter(
            FeatureBacklog.title.ilike(like) | FeatureBacklog.description.ilike(like)
        )
        if project_id:
            fq = fq.filter(FeatureBacklog.project_id == project_id)
        for f in fq.limit(limit).all():
            results.append({
                "type": "feature",
                "id": f.id,
                "title": f.title,
                "subtitle": f"Backlog · {f.status}",
                "snippet": _snippet(f.description, term),
                "route": "/backlog",
                "project_id": f.project_id,
            })

        # -- Runs ------------------------------------------------------------
        rq = s.query(Run).filter(Run.label.ilike(like))
        if project_id:
            rq = rq.filter(Run.project_id == project_id)
        for r in rq.order_by(Run.started_at.desc()).limit(limit).all():
            results.append({
                "type": "run",
                "id": r.id,
                "title": r.label,
                "subtitle": f"Run · {r.kind} · {r.status}",
                "snippet": "",
                "route": "/logs",
                "project_id": r.project_id,
            })

    # Title matches first, then by type; keeps the most obvious hits on top.
    order = {"project": 0, "document": 1, "feature": 2, "run": 3}
    results.sort(
        key=lambda r: (
            0 if term.lower() in (r["title"] or "").lower() else 1,
            order.get(r["type"], 9),
        )
    )
    return {"query": term, "count": len(results), "results": results[:limit]}
