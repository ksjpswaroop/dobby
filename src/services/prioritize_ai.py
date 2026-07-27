"""
AI-assisted prioritization (100-Day Roadmap, Day 23).

Suggestions are *proposals*, never writes. The model reads a feature and its
linked documents and proposes impact/effort/risk; the user accepts, edits, or
rejects. Nothing touches the real Pareto score until they do.

That is the same propose-don't-act shape used by Research's feature
acceptance and the Inbox — a scoring model that silently reorders your
backlog is one you stop trusting the moment it gets one wrong.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.db.copilot_models import ScoreSuggestion
from src.db.schema import DatabaseManager, FeatureBacklog, Node
from src.services import model_routing

logger = structlog.get_logger()


class PrioritizeError(Exception):
    pass


def _clamp(value: Any, default: int = 5) -> int:
    try:
        return max(1, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Models wrap JSON in prose and fences; find the first real object."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if not candidate:
        brace = re.search(r"\{.*\}", text, re.S)
        candidate = brace.group(0) if brace else None
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _linked_context(db: DatabaseManager, feature: FeatureBacklog, limit: int = 3) -> str:
    """Documents that mention this feature, as evidence for the estimate."""
    with db.get_session() as s:
        nodes = s.query(Node).filter(Node.project_id == feature.project_id).all()
    needle = (feature.title or "").lower()
    hits = [n for n in nodes if needle and needle in ((n.title or "") + (n.content or "")).lower()]
    if not hits:
        return ""
    return "\n\n".join(f"### {n.title}\n{(n.content or '')[:800]}" for n in hits[:limit])


async def suggest_scores(db: DatabaseManager, project_id: str, feature_id: str,
                         model: str = "") -> Dict[str, Any]:
    with db.get_session() as s:
        feature = s.get(FeatureBacklog, feature_id)
        if not feature or feature.project_id != project_id:
            raise PrioritizeError("Feature not found in this project.")
        title = feature.title
        description = feature.description or ""
        current = (feature.impact_score, feature.effort_score, feature.risk_score)

    with db.get_session() as s:
        feature = s.get(FeatureBacklog, feature_id)
        context = _linked_context(db, feature)

    prompt = (
        "Estimate scores for this product feature on a 1-10 scale.\n\n"
        f"Feature: {title}\n"
        f"Description: {description[:1500]}\n"
        + (f"\nRelated documents:\n{context}\n" if context else "")
        + "\nRespond with ONLY this JSON object, no prose:\n"
        '{"impact": <1-10>, "effort": <1-10>, "risk": <1-10>, '
        '"confidence": <0.0-1.0>, "rationale": "<one or two sentences>"}\n\n'
        "impact = value to users if built. effort = work required. "
        "risk = chance it goes wrong or is harder than it looks."
    )

    try:
        raw = await model_routing.call(db, "prioritize", prompt, model=model,
                                       project_id=project_id, max_tokens=500,
                                       temperature=0.2, json_mode=True)
    except Exception as e:
        raise PrioritizeError(f"The model could not be reached: {e}")

    parsed = _extract_json(raw)
    if not parsed:
        raise PrioritizeError("The model did not return usable scores.")

    suggestion = ScoreSuggestion(
        id=str(uuid.uuid4()), project_id=project_id, feature_id=feature_id,
        current_impact=current[0], current_effort=current[1], current_risk=current[2],
        suggested_impact=_clamp(parsed.get("impact")),
        suggested_effort=_clamp(parsed.get("effort")),
        suggested_risk=_clamp(parsed.get("risk")),
        rationale=str(parsed.get("rationale", ""))[:1000],
        confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.5) or 0.5))),
        status="pending",
    )
    with db.get_session() as s:
        s.add(suggestion)
        s.commit()
        return _suggestion_dict(suggestion, title)


def _suggestion_dict(sug: ScoreSuggestion, title: str = "") -> Dict[str, Any]:
    def pareto(i, e, r):
        return (i * 0.6) - (e * 0.3) - (r * 0.1)

    return {
        "id": sug.id,
        "feature_id": sug.feature_id,
        "feature_title": title,
        "current": {"impact": sug.current_impact, "effort": sug.current_effort,
                    "risk": sug.current_risk,
                    "pareto": round(pareto(sug.current_impact or 5, sug.current_effort or 5,
                                           sug.current_risk or 5), 2)},
        "suggested": {"impact": sug.suggested_impact, "effort": sug.suggested_effort,
                      "risk": sug.suggested_risk,
                      "pareto": round(pareto(sug.suggested_impact, sug.suggested_effort,
                                             sug.suggested_risk), 2)},
        "rationale": sug.rationale,
        "confidence": sug.confidence,
        "status": sug.status,
        "created_at": sug.created_at.isoformat() if sug.created_at else None,
    }


def list_suggestions(db: DatabaseManager, project_id: str,
                     status: str = "pending") -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(ScoreSuggestion)
                .filter(ScoreSuggestion.project_id == project_id,
                        ScoreSuggestion.status == status)
                .order_by(ScoreSuggestion.created_at.desc()).all())
        titles = {f.id: f.title for f in
                  s.query(FeatureBacklog).filter(FeatureBacklog.project_id == project_id).all()}
        return [_suggestion_dict(r, titles.get(r.feature_id, "")) for r in rows]


def accept(db: DatabaseManager, suggestion_id: str,
           impact: Optional[int] = None, effort: Optional[int] = None,
           risk: Optional[int] = None) -> Dict[str, Any]:
    """Apply a suggestion, optionally with the user's own edits to the numbers."""
    with db.get_session() as s:
        sug = s.get(ScoreSuggestion, suggestion_id)
        if not sug:
            raise PrioritizeError("Suggestion not found.")
        if sug.status != "pending":
            raise PrioritizeError("That suggestion has already been decided.")
        feature = s.get(FeatureBacklog, sug.feature_id)
        if not feature:
            raise PrioritizeError("The feature no longer exists.")

        feature.impact_score = _clamp(impact if impact is not None else sug.suggested_impact)
        feature.effort_score = _clamp(effort if effort is not None else sug.suggested_effort)
        feature.risk_score = _clamp(risk if risk is not None else sug.suggested_risk)
        feature.pareto_score = float(
            (feature.impact_score * 0.6) - (feature.effort_score * 0.3)
            - (feature.risk_score * 0.1)
        )
        sug.status = "accepted"
        s.commit()
        return {
            "feature_id": feature.id, "title": feature.title,
            "impact": feature.impact_score, "effort": feature.effort_score,
            "risk": feature.risk_score, "pareto": round(feature.pareto_score, 2),
        }


def reject(db: DatabaseManager, suggestion_id: str) -> bool:
    with db.get_session() as s:
        sug = s.get(ScoreSuggestion, suggestion_id)
        if not sug or sug.status != "pending":
            return False
        sug.status = "rejected"
        s.commit()
        return True
