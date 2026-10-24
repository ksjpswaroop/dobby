"""
Auto work-breakdown (100-Day Roadmap, Day 46).

Decomposes a large backlog item into concrete subtasks using the local model.
Like every other AI feature in Dobby this **proposes** — the subtasks come
back for review and are only written to the backlog when the user accepts.

Subtasks are inserted as real `FeatureBacklog` rows with seed Pareto scores,
and any suggested ordering becomes real `Blocker` rows, so the breakdown
lands in the same board, roadmap, and analytics as everything else rather
than in a parallel to-do list nobody looks at.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.db.planning_models import Blocker, PlanningMeta
from src.db.schema import DatabaseManager, FeatureBacklog, Node
from src.services import model_routing

logger = structlog.get_logger()

MAX_SUBTASKS = 12


class WBSError(Exception):
    pass


def _clamp(v: Any, default: int = 5) -> int:
    try:
        return max(1, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if not candidate:
        m = re.search(r"\[.*\]", text, re.S)
        candidate = m.group(0) if m else None
    if not candidate:
        # Some models wrap the array in an object.
        obj = re.search(r"\{.*\}", text, re.S)
        if obj:
            try:
                parsed = json.loads(obj.group(0))
                for key in ("subtasks", "tasks", "items"):
                    if isinstance(parsed.get(key), list):
                        return parsed[key]
            except json.JSONDecodeError:
                return None
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


async def propose(db: DatabaseManager, project_id: str, feature_id: str,
                  model: str = "") -> Dict[str, Any]:
    """Ask the model for a breakdown. Writes nothing."""
    with db.get_session() as s:
        feature = s.get(FeatureBacklog, feature_id)
        if not feature or feature.project_id != project_id:
            raise WBSError("Feature not found in this project.")
        title, description = feature.title, feature.description or ""

        # Any generated document that mentions this feature is useful context.
        nodes = s.query(Node).filter(Node.project_id == project_id).all()

    needle = (title or "").lower()
    related = [n for n in nodes
               if needle and needle in ((n.title or "") + (n.content or "")).lower()]
    context = "\n\n".join(f"### {n.title}\n{(n.content or '')[:700]}"
                          for n in related[:2])

    prompt = (
        f"Break this piece of work into concrete, independently completable subtasks.\n\n"
        f"Work item: {title}\nDescription: {description[:1500]}\n"
        + (f"\nRelated documents:\n{context}\n" if context else "")
        + f"\nReturn ONLY a JSON array of at most {MAX_SUBTASKS} objects, no prose:\n"
        '[{"title": "...", "impact": 1-10, "effort": 1-10, "risk": 1-10, '
        '"depends_on": ["<title of an earlier subtask>"]}]\n\n'
        "Each title must be a specific action, not a restatement of the parent. "
        "Use depends_on only when one subtask genuinely cannot start before another."
    )

    try:
        raw = await model_routing.call(db, "generate", prompt, model=model,
                                       project_id=project_id, max_tokens=1500,
                                       temperature=0.3, json_mode=True)
    except Exception as e:
        raise WBSError(f"The model could not be reached: {e}")

    parsed = _extract_json_array(raw)
    if not parsed:
        raise WBSError("The model did not return a usable breakdown.")

    subtasks = []
    for item in parsed[:MAX_SUBTASKS]:
        if not isinstance(item, dict):
            continue
        st_title = str(item.get("title", "")).strip()
        if not st_title:
            continue
        impact, effort, risk = (_clamp(item.get("impact")), _clamp(item.get("effort")),
                                _clamp(item.get("risk")))
        subtasks.append({
            "title": st_title[:200],
            "impact": impact, "effort": effort, "risk": risk,
            "pareto": round((impact * 0.6) - (effort * 0.3) - (risk * 0.1), 2),
            "depends_on": [str(d).strip() for d in (item.get("depends_on") or [])
                           if str(d).strip()],
        })

    if not subtasks:
        raise WBSError("The model returned no usable subtasks.")

    return {"parent_id": feature_id, "parent_title": title, "subtasks": subtasks}


def accept(db: DatabaseManager, project_id: str, parent_id: str,
           subtasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write accepted subtasks as real backlog features and blocker edges."""
    if not subtasks:
        raise WBSError("Nothing to accept.")

    created: List[Dict[str, Any]] = []
    by_title: Dict[str, str] = {}

    with db.get_session() as s:
        parent = s.get(FeatureBacklog, parent_id)
        if not parent or parent.project_id != project_id:
            raise WBSError("Parent feature not found in this project.")

        for st in subtasks:
            title = str(st.get("title", "")).strip()
            if not title:
                continue
            impact, effort, risk = (_clamp(st.get("impact")), _clamp(st.get("effort")),
                                    _clamp(st.get("risk")))
            fid = str(uuid.uuid4())
            s.add(FeatureBacklog(
                id=fid, project_id=project_id, title=title[:200],
                description=f"Subtask of: {parent.title}",
                category="subtask", impact_score=impact, effort_score=effort,
                risk_score=risk,
                pareto_score=(impact * 0.6) - (effort * 0.3) - (risk * 0.1),
                status="backlog",
            ))
            # Flush before the PlanningMeta row: its feature_id is a foreign
            # key to the feature above, and SQLAlchemy does not guarantee it
            # inserts the parent first when both are pending in one batch.
            s.flush()
            s.add(PlanningMeta(feature_id=fid, project_id=project_id,
                               board_column="backlog", estimate=float(effort),
                               estimate_unit="points"))
            by_title[title.lower()] = fid
            created.append({"feature_id": fid, "title": title})
        s.flush()

        # Second pass: dependencies can only be resolved once every subtask
        # has an id.
        edges = 0
        for st in subtasks:
            fid = by_title.get(str(st.get("title", "")).strip().lower())
            if not fid:
                continue
            for dep_title in (st.get("depends_on") or []):
                dep_id = by_title.get(str(dep_title).strip().lower())
                if dep_id and dep_id != fid:
                    s.add(Blocker(id=str(uuid.uuid4()), project_id=project_id,
                                  feature_id=fid, blocked_by_id=dep_id,
                                  note="from work breakdown"))
                    edges += 1
        s.commit()

    return {"created": created, "count": len(created), "dependencies": edges}
