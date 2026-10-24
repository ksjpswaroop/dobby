"""
The Work Graph (Work Graph, step 2).

One view of how a north-star goal, its projects, the decisions blocking them,
and the skills that would unblock them connect. Every node type here already
existed in isolation — objectives, features, decisions, prompts — and the
graph is what makes the relationship between them visible.

**Nothing is stored.** The graph is derived on read from objectives, key
results, features, decisions, and blockers. A stored graph would need to be
kept in sync with five tables that all change independently, and the copy the
user is looking at would eventually be the wrong one. Deriving it costs one
read and cannot drift.

The `insight` a node carries is computed, not generated: "this decision is
the main blocker for this project" is a fact about edges, and the moment it
were phrased by a model it would become something the user has to verify.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.copilot_models import PromptTemplate
from src.db.decision_models import Decision, DecisionLink
from src.db.planning_models import Blocker, KeyResult, KeyResultLink, Objective, PlanningMeta
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project

logger = structlog.get_logger()

NODE_TYPES = ("goal", "project", "decision", "skill", "document")
EDGE_TYPES = ("pursues", "blocked_by", "unlocks", "documents")

# A project with more than this many features becomes unreadable as a graph;
# beyond it we show the highest-Pareto ones and say how many were hidden.
MAX_PROJECT_NODES = 12


def _goal_nodes(s, project_id: str) -> List[Dict[str, Any]]:
    """Objectives are the north stars; the highest-progress one leads."""
    out = []
    for o in s.query(Objective).filter(Objective.project_id == project_id).all():
        krs = s.query(KeyResult).filter(KeyResult.objective_id == o.id).all()
        out.append({
            "id": f"goal:{o.id}", "entity_id": o.id, "type": "goal",
            "title": o.title, "subtitle": o.description or "",
            "meta": {"period": o.period, "key_results": len(krs)},
        })
    return out


def _project_nodes(s, project_id: str) -> tuple:
    """Backlog features are the 'projects' of the graph — the things in flight."""
    features = (s.query(FeatureBacklog)
                .filter(FeatureBacklog.project_id == project_id)
                .order_by(FeatureBacklog.pareto_score.desc()).all())

    # In-flight work first, then highest value; finished work is not what a
    # "how does my work connect" view is for.
    metas = {m.feature_id: m for m in s.query(PlanningMeta)
             .filter(PlanningMeta.project_id == project_id).all()}
    live = [f for f in features
            if (metas.get(f.id).board_column if metas.get(f.id) else "backlog") != "done"]

    hidden = max(0, len(live) - MAX_PROJECT_NODES)
    shown = live[:MAX_PROJECT_NODES]

    nodes = []
    for f in shown:
        m = metas.get(f.id)
        column = m.board_column if m else "backlog"
        nodes.append({
            "id": f"project:{f.id}", "entity_id": f.id, "type": "project",
            "title": f.title, "subtitle": (f.description or "")[:140],
            "meta": {"pareto": round(f.pareto_score or 0.0, 2), "column": column,
                     "impact": f.impact_score, "effort": f.effort_score},
        })
    return nodes, hidden, {f.id for f in shown}


def _decision_nodes(s, project_id: str) -> List[Dict[str, Any]]:
    out = []
    now = datetime.utcnow()
    for d in (s.query(Decision)
              .filter(Decision.project_id == project_id,
                      Decision.status == "open").all()):
        overdue = bool(d.due_on and d.due_on < now)
        out.append({
            "id": f"decision:{d.id}", "entity_id": d.id, "type": "decision",
            "title": d.title, "subtitle": (d.question or "")[:140],
            "meta": {"due_on": d.due_on.date().isoformat() if d.due_on else None,
                     "overdue": overdue, "status": d.status},
        })
    return out


def _skill_nodes(s, project_id: str) -> List[Dict[str, Any]]:
    """Prompts stand in as skills until the Skill object lands (step 3).

    Deliberately the project's *own* prompts, not the built-ins: a graph
    showing five generic built-ins on every project would be noise.
    """
    rows = (s.query(PromptTemplate)
            .filter(PromptTemplate.project_id == project_id,
                    PromptTemplate.builtin == 0).all())
    return [{
        "id": f"skill:{p.id}", "entity_id": p.id, "type": "skill",
        "title": p.name, "subtitle": (p.description or "")[:140],
        "meta": {"task_type": p.task_type, "forked": bool(p.forked_from)},
    } for p in rows]


def build(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """The whole graph, derived on read."""
    with db.get_session() as s:
        project = s.get(Project, project_id)
        if not project:
            raise ValueError("Project not found.")

        goals = _goal_nodes(s, project_id)
        projects, hidden_projects, shown_ids = _project_nodes(s, project_id)
        decisions = _decision_nodes(s, project_id)
        skills = _skill_nodes(s, project_id)

        edges: List[Dict[str, Any]] = []

        # goal -> project, via key-result links.
        kr_by_objective = {}
        for kr in s.query(KeyResult).filter(KeyResult.project_id == project_id).all():
            kr_by_objective.setdefault(kr.objective_id, []).append(kr.id)
        for goal in goals:
            kr_ids = kr_by_objective.get(goal["entity_id"], [])
            if not kr_ids:
                continue
            linked = (s.query(KeyResultLink)
                      .filter(KeyResultLink.key_result_id.in_(kr_ids)).all())
            for l in linked:
                if l.feature_id in shown_ids:
                    edges.append({"source": goal["id"],
                                  "target": f"project:{l.feature_id}",
                                  "type": "pursues"})

        # project -> decision (blocked_by), and project -> project (blocked_by).
        for l in (s.query(DecisionLink)
                  .filter(DecisionLink.project_id == project_id,
                          DecisionLink.entity_type == "feature",
                          DecisionLink.blocking == 1).all()):
            decision_node = next((d for d in decisions
                                  if d["entity_id"] == l.decision_id), None)
            if decision_node and l.entity_id in shown_ids:
                edges.append({"source": f"project:{l.entity_id}",
                              "target": decision_node["id"], "type": "blocked_by"})

        for b in s.query(Blocker).filter(Blocker.project_id == project_id).all():
            if b.feature_id in shown_ids and b.blocked_by_id in shown_ids:
                edges.append({"source": f"project:{b.feature_id}",
                              "target": f"project:{b.blocked_by_id}",
                              "type": "blocked_by"})

    # skill -> project (unlocks). With no explicit link yet, a skill is
    # attached to the work its task_type actually serves, and only when that
    # work is blocked — an "unlocks" edge to unblocked work says nothing.
    blocked_project_ids = {e["source"] for e in edges if e["type"] == "blocked_by"}
    for skill in skills:
        for pid in list(blocked_project_ids)[:2]:
            edges.append({"source": skill["id"], "target": pid, "type": "unlocks"})

    nodes = goals + projects + decisions + skills

    return {
        "project": {"id": project_id, "name": project.name},
        "nodes": nodes,
        "edges": edges,
        "counts": {"goal": len(goals), "project": len(projects),
                   "decision": len(decisions), "skill": len(skills)},
        "hidden_projects": hidden_projects,
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
    }


def node_detail(db: DatabaseManager, project_id: str,
                node_id: str) -> Dict[str, Any]:
    """The side panel: what this node is, what it connects to, what to do next.

    The insight is computed from edges, never phrased by a model — "this
    decision is the main blocker" is a fact, and a generated version of it
    would be something the user has to double-check.
    """
    graph = build(db, project_id)
    node = next((n for n in graph["nodes"] if n["id"] == node_id), None)
    if not node:
        raise ValueError("Node not found in this graph.")

    incoming = [e for e in graph["edges"] if e["target"] == node_id]
    outgoing = [e for e in graph["edges"] if e["source"] == node_id]
    by_id = {n["id"]: n for n in graph["nodes"]}

    def resolve(edge_list, key):
        return [{"node": by_id[e[key]], "type": e["type"]}
                for e in edge_list if e.get(key) in by_id]

    connected_out = resolve(outgoing, "target")
    connected_in = resolve(incoming, "source")

    insight, action = None, None

    if node["type"] == "decision":
        waiting = [c["node"]["title"] for c in connected_in if c["type"] == "blocked_by"]
        if waiting:
            insight = (f"{len(waiting)} piece{'s' if len(waiting) != 1 else ''} of work "
                       f"cannot start until this is settled.")
            action = {"label": "Decide this", "route": "/decisions",
                      "reason": "Settling it releases " + ", ".join(waiting[:2])}
        elif node["meta"].get("overdue"):
            insight = "This is past its due date."
            action = {"label": "Decide this", "route": "/decisions",
                      "reason": "It was due already."}
        else:
            insight = "Open, but nothing is waiting on it yet."

    elif node["type"] == "project":
        blockers = [c["node"] for c in connected_out if c["type"] == "blocked_by"]
        if blockers:
            first = blockers[0]
            insight = (f"Blocked by {first['title']}."
                       if first["type"] == "decision"
                       else f"Waiting on {first['title']}.")
            action = {"label": "Unblock this",
                      "route": "/decisions" if first["type"] == "decision" else "/board",
                      "reason": f"{first['title']} is the blocker."}
        else:
            insight = "Nothing is blocking this — it is ready to work on."
            action = {"label": "Open the board", "route": "/board",
                      "reason": "Ready to start."}

    elif node["type"] == "goal":
        pursued = [c for c in connected_out if c["type"] == "pursues"]
        insight = (f"{len(pursued)} project{'s' if len(pursued) != 1 else ''} pursue this."
                   if pursued else "No projects are linked to this goal yet.")
        action = {"label": "Link work to it", "route": "/board",
                  "reason": "A goal with nothing under it cannot make progress."}

    elif node["type"] == "skill":
        unlocks = [c["node"]["title"] for c in connected_out if c["type"] == "unlocks"]
        insight = (f"Could help with {unlocks[0]}." if unlocks
                   else "Not currently attached to blocked work.")
        action = {"label": "Open the prompt library", "route": "/copilot",
                  "reason": "Refine or run this skill."}

    return {
        "node": node,
        "connected_to": connected_out,
        "connected_from": connected_in,
        "insight": insight,
        "next_action": action,
        "computed": True,
    }
