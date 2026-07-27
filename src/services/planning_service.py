"""
Planning & PM (100-Day Roadmap, Days 41-50, excluding WBS and analytics).

Two rules run through everything here:

**Blocked is derived, never stored as a column value.** A feature is blocked
if it has an unfinished blocker, full stop. Storing "blocked" as a board
column *and* keeping blocker rows would let the two disagree, and the one the
user sees would eventually be the wrong one. `board_column` therefore never
holds "blocked"; the board computes it.

**Every column move is recorded.** Velocity, throughput, and cycle time are
questions about *when* work moved, which current state cannot answer, so
`_move()` is the only way a column changes and it always appends a row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from src.db.planning_models import (
    BOARD_COLUMNS, ESTIMATE_UNITS, SPRINT_STATES, STATUS_TO_COLUMN,
    Blocker, DailyPlan, FeatureStatusChange, KeyResult, KeyResultLink,
    Milestone, Objective, PlanningMeta, Sprint,
)
from src.db.schema import DatabaseManager, FeatureBacklog, Project

DEFAULT_DAILY_CAPACITY = 3.0


class PlanningError(Exception):
    pass


# ---------------------------------------------------------------------------
# Meta helpers
# ---------------------------------------------------------------------------
def _meta(s, feature: FeatureBacklog) -> PlanningMeta:
    m = s.get(PlanningMeta, feature.id)
    if not m:
        m = PlanningMeta(
            feature_id=feature.id, project_id=feature.project_id,
            board_column=STATUS_TO_COLUMN.get(feature.status or "backlog", "backlog"),
            # The Pareto effort input is a perfectly good seed estimate; the
            # user refines it rather than starting from nothing.
            estimate=float(feature.effort_score or 5),
            estimate_unit="points",
        )
        s.add(m)
        s.flush()
    return m


def _blocked_ids(s, project_id: str) -> Set[str]:
    """Features with at least one blocker that is not yet done."""
    rows = s.query(Blocker).filter(Blocker.project_id == project_id).all()
    if not rows:
        return set()
    upstream_ids = {r.blocked_by_id for r in rows}
    done: Set[str] = set()
    for m in s.query(PlanningMeta).filter(PlanningMeta.feature_id.in_(upstream_ids)).all():
        if m.board_column == "done":
            done.add(m.feature_id)
    for f in s.query(FeatureBacklog).filter(FeatureBacklog.id.in_(upstream_ids)).all():
        if f.status in ("completed", "skipped"):
            done.add(f.id)
    return {r.feature_id for r in rows if r.blocked_by_id not in done}


def _card(f: FeatureBacklog, m: PlanningMeta, blocked: bool) -> Dict[str, Any]:
    return {
        "feature_id": f.id,
        "title": f.title,
        "category": f.category,
        "pareto_score": round(f.pareto_score or 0.0, 2),
        "impact": f.impact_score, "effort": f.effort_score, "risk": f.risk_score,
        "column": "blocked" if blocked else (m.board_column or "backlog"),
        "stored_column": m.board_column or "backlog",
        "blocked": blocked,
        "estimate": m.estimate,
        "estimate_unit": m.estimate_unit or "points",
        "sprint_id": m.sprint_id,
        "milestone_id": m.milestone_id,
        "order_index": m.order_index or 0,
        "node_id": f.node_id,
    }


# ---------------------------------------------------------------------------
# Board (D41, D44)
# ---------------------------------------------------------------------------
def get_board(db: DatabaseManager, project_id: str,
              sprint_id: Optional[str] = None) -> Dict[str, Any]:
    with db.get_session() as s:
        features = (s.query(FeatureBacklog)
                    .filter(FeatureBacklog.project_id == project_id).all())
        blocked = _blocked_ids(s, project_id)

        columns: Dict[str, List[Dict[str, Any]]] = {c: [] for c in BOARD_COLUMNS}
        for f in features:
            m = _meta(s, f)
            if sprint_id and m.sprint_id != sprint_id:
                continue
            card = _card(f, m, f.id in blocked)
            columns[card["column"]].append(card)
        s.commit()

    for col in columns.values():
        col.sort(key=lambda c: (c["order_index"], -c["pareto_score"]))

    return {
        "columns": [{"id": c, "title": c.replace("_", " ").title(),
                     "cards": columns[c], "count": len(columns[c])}
                    for c in BOARD_COLUMNS],
        "total": sum(len(v) for v in columns.values()),
    }


def _move(s, feature: FeatureBacklog, to_column: str,
          order_index: Optional[int] = None) -> PlanningMeta:
    m = _meta(s, feature)
    previous = m.board_column
    m.board_column = to_column
    if order_index is not None:
        m.order_index = order_index

    now = datetime.utcnow()
    if to_column == "in_progress" and not m.started_at:
        m.started_at = now
    if to_column == "done":
        m.completed_at = now
        feature.status = "completed"
        feature.completed_at = now
    elif feature.status == "completed":
        # Pulling something back out of Done has to undo the completion too,
        # or the backlog and the board disagree.
        feature.status = "in_progress" if to_column == "in_progress" else "backlog"
        feature.completed_at = None
        m.completed_at = None

    if previous != to_column:
        s.add(FeatureStatusChange(
            id=str(uuid.uuid4()), project_id=feature.project_id, feature_id=feature.id,
            from_column=previous, to_column=to_column, sprint_id=m.sprint_id,
            estimate=m.estimate, created_at=now,
        ))
    return m


def move_card(db: DatabaseManager, feature_id: str, to_column: str,
              order_index: Optional[int] = None) -> Dict[str, Any]:
    if to_column not in BOARD_COLUMNS:
        raise PlanningError(f"Unknown column. One of: {', '.join(BOARD_COLUMNS)}")
    if to_column == "blocked":
        raise PlanningError(
            "Blocked is derived from blockers, not set directly. Add a blocker instead."
        )
    with db.get_session() as s:
        f = s.get(FeatureBacklog, feature_id)
        if not f:
            raise PlanningError("Feature not found.")
        m = _move(s, f, to_column, order_index)
        blocked = feature_id in _blocked_ids(s, f.project_id)
        s.commit()
        return _card(f, m, blocked)


# ---------------------------------------------------------------------------
# Blockers (D44)
# ---------------------------------------------------------------------------
def _would_cycle(s, project_id: str, feature_id: str, blocked_by_id: str) -> bool:
    """Walk upstream from the proposed blocker looking for the feature itself."""
    edges: Dict[str, List[str]] = {}
    for b in s.query(Blocker).filter(Blocker.project_id == project_id).all():
        edges.setdefault(b.feature_id, []).append(b.blocked_by_id)

    seen, stack = set(), [blocked_by_id]
    while stack:
        node = stack.pop()
        if node == feature_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    return False


def add_blocker(db: DatabaseManager, project_id: str, feature_id: str,
                blocked_by_id: str, note: str = "") -> Dict[str, Any]:
    if feature_id == blocked_by_id:
        raise PlanningError("A feature cannot block itself.")
    with db.get_session() as s:
        for fid in (feature_id, blocked_by_id):
            f = s.get(FeatureBacklog, fid)
            if not f or f.project_id != project_id:
                raise PlanningError("Feature not found in this project.")
        if _would_cycle(s, project_id, feature_id, blocked_by_id):
            raise PlanningError("That would create a circular dependency.")
        existing = (s.query(Blocker)
                    .filter(Blocker.feature_id == feature_id,
                            Blocker.blocked_by_id == blocked_by_id).first())
        if not existing:
            s.add(Blocker(id=str(uuid.uuid4()), project_id=project_id,
                          feature_id=feature_id, blocked_by_id=blocked_by_id,
                          note=note[:300]))
            s.commit()
    return list_blockers(db, project_id, feature_id)


def remove_blocker(db: DatabaseManager, blocker_id: str) -> bool:
    with db.get_session() as s:
        b = s.get(Blocker, blocker_id)
        if not b:
            return False
        s.delete(b)
        s.commit()
        return True


def list_blockers(db: DatabaseManager, project_id: str,
                  feature_id: Optional[str] = None) -> Dict[str, Any]:
    with db.get_session() as s:
        q = s.query(Blocker).filter(Blocker.project_id == project_id)
        if feature_id:
            q = q.filter(Blocker.feature_id == feature_id)
        rows = q.all()
        titles = {f.id: f.title for f in
                  s.query(FeatureBacklog)
                  .filter(FeatureBacklog.project_id == project_id).all()}
        blocked = _blocked_ids(s, project_id)
        return {
            "blockers": [{
                "id": b.id, "feature_id": b.feature_id,
                "feature_title": titles.get(b.feature_id, ""),
                "blocked_by_id": b.blocked_by_id,
                "blocked_by_title": titles.get(b.blocked_by_id, ""),
                "note": b.note,
                "still_blocking": b.feature_id in blocked,
            } for b in rows],
            "blocked_feature_ids": sorted(blocked),
        }


def ready_features(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    """Unblocked, unfinished work, best value first — the ready set."""
    with db.get_session() as s:
        blocked = _blocked_ids(s, project_id)
        features = (s.query(FeatureBacklog)
                    .filter(FeatureBacklog.project_id == project_id).all())
        out = []
        for f in features:
            m = _meta(s, f)
            if m.board_column == "done" or f.id in blocked:
                continue
            out.append(_card(f, m, False))
        s.commit()
    out.sort(key=lambda c: -c["pareto_score"])
    return out


# ---------------------------------------------------------------------------
# Estimates (D45)
# ---------------------------------------------------------------------------
def set_estimate(db: DatabaseManager, feature_id: str, estimate: float,
                 unit: str = "points") -> Dict[str, Any]:
    if unit not in ESTIMATE_UNITS:
        raise PlanningError(f"Unknown unit. One of: {', '.join(ESTIMATE_UNITS)}")
    if estimate < 0:
        raise PlanningError("An estimate cannot be negative.")
    with db.get_session() as s:
        f = s.get(FeatureBacklog, feature_id)
        if not f:
            raise PlanningError("Feature not found.")
        m = _meta(s, f)
        m.estimate = float(estimate)
        m.estimate_unit = unit
        blocked = feature_id in _blocked_ids(s, f.project_id)
        s.commit()
        return _card(f, m, blocked)


# ---------------------------------------------------------------------------
# Sprints (D43, D45)
# ---------------------------------------------------------------------------
def create_sprint(db: DatabaseManager, project_id: str, name: str,
                  starts_on: str, ends_on: str, goal: str = "",
                  capacity: float = 0.0) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise PlanningError("A sprint needs a name.")
    try:
        start = datetime.fromisoformat(starts_on)
        end = datetime.fromisoformat(ends_on)
    except ValueError:
        raise PlanningError("Dates must be ISO format (YYYY-MM-DD).")
    if end <= start:
        raise PlanningError("A sprint must end after it starts.")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise PlanningError("Project not found.")
        sp = Sprint(id=str(uuid.uuid4()), project_id=project_id, name=name[:120],
                    goal=goal[:1000], starts_on=start, ends_on=end,
                    capacity=float(capacity or 0.0), state="planned")
        s.add(sp)
        s.commit()
        return _sprint_dict(sp)


def _sprint_dict(sp: Sprint) -> Dict[str, Any]:
    return {
        "id": sp.id, "name": sp.name, "goal": sp.goal, "state": sp.state,
        "starts_on": sp.starts_on.date().isoformat() if sp.starts_on else None,
        "ends_on": sp.ends_on.date().isoformat() if sp.ends_on else None,
        "capacity": sp.capacity,
    }


def list_sprints(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(Sprint).filter(Sprint.project_id == project_id)
                .order_by(Sprint.starts_on.desc()).all())
        return [_sprint_dict(sp) for sp in rows]


def set_sprint_state(db: DatabaseManager, sprint_id: str, state: str) -> Dict[str, Any]:
    if state not in SPRINT_STATES:
        raise PlanningError(f"Unknown state. One of: {', '.join(SPRINT_STATES)}")
    with db.get_session() as s:
        sp = s.get(Sprint, sprint_id)
        if not sp:
            raise PlanningError("Sprint not found.")
        if state == "active":
            # Two active sprints makes "the current sprint" ambiguous
            # everywhere it is used, so activating one closes the others.
            for other in (s.query(Sprint)
                          .filter(Sprint.project_id == sp.project_id,
                                  Sprint.state == "active",
                                  Sprint.id != sprint_id).all()):
                other.state = "closed"
                other.closed_at = datetime.utcnow()
        sp.state = state
        if state == "closed":
            sp.closed_at = datetime.utcnow()
        s.commit()
        return _sprint_dict(sp)


def assign_to_sprint(db: DatabaseManager, feature_id: str,
                     sprint_id: Optional[str]) -> Dict[str, Any]:
    with db.get_session() as s:
        f = s.get(FeatureBacklog, feature_id)
        if not f:
            raise PlanningError("Feature not found.")
        if sprint_id:
            sp = s.get(Sprint, sprint_id)
            if not sp or sp.project_id != f.project_id:
                raise PlanningError("Sprint not found in this project.")
        m = _meta(s, f)
        m.sprint_id = sprint_id
        blocked = feature_id in _blocked_ids(s, f.project_id)
        s.commit()
        return _card(f, m, blocked)


def sprint_summary(db: DatabaseManager, sprint_id: str) -> Dict[str, Any]:
    """Committed vs completed against capacity."""
    with db.get_session() as s:
        sp = s.get(Sprint, sprint_id)
        if not sp:
            raise PlanningError("Sprint not found.")
        metas = s.query(PlanningMeta).filter(PlanningMeta.sprint_id == sprint_id).all()
        ids = [m.feature_id for m in metas]
        features = {f.id: f for f in s.query(FeatureBacklog)
                    .filter(FeatureBacklog.id.in_(ids)).all()} if ids else {}

        committed = sum(m.estimate or 0.0 for m in metas)
        completed = sum(m.estimate or 0.0 for m in metas if m.board_column == "done")
        done_count = sum(1 for m in metas if m.board_column == "done")

        return {
            "sprint": _sprint_dict(sp),
            "item_count": len(metas),
            "completed_count": done_count,
            "committed_estimate": round(committed, 2),
            "completed_estimate": round(completed, 2),
            "capacity": sp.capacity,
            "over_capacity": bool(sp.capacity and committed > sp.capacity),
            "remaining_capacity": round((sp.capacity or 0.0) - committed, 2),
            "items": [{
                "feature_id": m.feature_id,
                "title": features.get(m.feature_id).title if m.feature_id in features else "",
                "estimate": m.estimate, "column": m.board_column,
            } for m in metas],
        }


# ---------------------------------------------------------------------------
# Milestones (D42, D43)
# ---------------------------------------------------------------------------
def create_milestone(db: DatabaseManager, project_id: str, name: str,
                     due_on: str, description: str = "") -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise PlanningError("A milestone needs a name.")
    try:
        due = datetime.fromisoformat(due_on)
    except ValueError:
        raise PlanningError("Due date must be ISO format (YYYY-MM-DD).")
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise PlanningError("Project not found.")
        ms = Milestone(id=str(uuid.uuid4()), project_id=project_id, name=name[:120],
                       description=description[:1000], due_on=due)
        s.add(ms)
        s.commit()
        return _milestone_dict(s, ms)


def _milestone_dict(s, ms: Milestone) -> Dict[str, Any]:
    metas = s.query(PlanningMeta).filter(PlanningMeta.milestone_id == ms.id).all()
    done = sum(1 for m in metas if m.board_column == "done")
    return {
        "id": ms.id, "name": ms.name, "description": ms.description,
        "due_on": ms.due_on.date().isoformat() if ms.due_on else None,
        "reached_at": ms.reached_at.isoformat() if ms.reached_at else None,
        "item_count": len(metas), "completed_count": done,
        "percent": round(100.0 * done / len(metas), 1) if metas else 0.0,
    }


def list_milestones(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(Milestone).filter(Milestone.project_id == project_id)
                .order_by(Milestone.due_on).all())
        return [_milestone_dict(s, ms) for ms in rows]


def assign_to_milestone(db: DatabaseManager, feature_id: str,
                        milestone_id: Optional[str]) -> Dict[str, Any]:
    with db.get_session() as s:
        f = s.get(FeatureBacklog, feature_id)
        if not f:
            raise PlanningError("Feature not found.")
        m = _meta(s, f)
        m.milestone_id = milestone_id
        blocked = feature_id in _blocked_ids(s, f.project_id)
        s.commit()
        return _card(f, m, blocked)


# ---------------------------------------------------------------------------
# Roadmap timeline (D42)
# ---------------------------------------------------------------------------
def timeline(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """Bars for sprints and milestones, plus dependency-ordered features.

    Features without dates are laid out by dependency depth: something that
    is blocked by two levels of prerequisites sits two slots to the right,
    which is the honest thing to draw when no real dates exist.
    """
    with db.get_session() as s:
        sprints = [_sprint_dict(sp) for sp in
                   s.query(Sprint).filter(Sprint.project_id == project_id)
                   .order_by(Sprint.starts_on).all()]
        milestones = [_milestone_dict(s, ms) for ms in
                      s.query(Milestone).filter(Milestone.project_id == project_id)
                      .order_by(Milestone.due_on).all()]

        blockers: Dict[str, List[str]] = {}
        for b in s.query(Blocker).filter(Blocker.project_id == project_id).all():
            blockers.setdefault(b.feature_id, []).append(b.blocked_by_id)

        features = (s.query(FeatureBacklog)
                    .filter(FeatureBacklog.project_id == project_id).all())

        depth_cache: Dict[str, int] = {}

        def depth(fid: str, seen: Optional[Set[str]] = None) -> int:
            if fid in depth_cache:
                return depth_cache[fid]
            seen = seen or set()
            if fid in seen:
                return 0  # cycles are prevented on write; be safe when drawing
            seen.add(fid)
            ups = blockers.get(fid, [])
            d = 0 if not ups else 1 + max(depth(u, seen) for u in ups)
            depth_cache[fid] = d
            return d

        bars = []
        for f in features:
            m = _meta(s, f)
            bars.append({
                "feature_id": f.id, "title": f.title, "category": f.category,
                "lane": depth(f.id),
                "estimate": m.estimate or 0.0,
                "column": m.board_column,
                "sprint_id": m.sprint_id, "milestone_id": m.milestone_id,
                "pareto_score": round(f.pareto_score or 0.0, 2),
            })
        s.commit()

    bars.sort(key=lambda b: (b["lane"], -b["pareto_score"]))
    return {"sprints": sprints, "milestones": milestones, "bars": bars,
            "max_lane": max([b["lane"] for b in bars], default=0)}


# ---------------------------------------------------------------------------
# Daily plan (D47)
# ---------------------------------------------------------------------------
def propose_daily_plan(db: DatabaseManager, project_id: str,
                       capacity: float = DEFAULT_DAILY_CAPACITY) -> Dict[str, Any]:
    """The highest-value ready work that fits today's capacity."""
    ready = ready_features(db, project_id)
    chosen, used = [], 0.0
    for card in ready:
        est = card["estimate"] or 1.0
        if used + est > capacity and chosen:
            break
        chosen.append({"feature_id": card["feature_id"], "title": card["title"],
                       "estimate": est, "pareto_score": card["pareto_score"],
                       "done": False})
        used += est
    return {"proposed": chosen, "capacity": capacity,
            "planned_estimate": round(used, 2), "ready_count": len(ready)}


def commit_daily_plan(db: DatabaseManager, project_id: str, plan_date: str,
                      items: List[Dict[str, Any]]) -> Dict[str, Any]:
    with db.get_session() as s:
        existing = (s.query(DailyPlan)
                    .filter(DailyPlan.project_id == project_id,
                            DailyPlan.plan_date == plan_date).first())
        payload = [{"feature_id": i.get("feature_id"), "title": i.get("title", ""),
                    "estimate": float(i.get("estimate") or 0), "done": bool(i.get("done"))}
                   for i in items]
        if existing:
            existing.items = payload
            plan = existing
        else:
            plan = DailyPlan(id=str(uuid.uuid4()), project_id=project_id,
                             plan_date=plan_date, items=payload)
            s.add(plan)
        s.commit()
        return {"id": plan.id, "plan_date": plan.plan_date, "items": plan.items}


def get_daily_plan(db: DatabaseManager, project_id: str,
                   plan_date: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        plan = (s.query(DailyPlan)
                .filter(DailyPlan.project_id == project_id,
                        DailyPlan.plan_date == plan_date).first())
        if not plan:
            return None
        items = plan.items or []
        done = sum(1 for i in items if i.get("done"))
        return {"id": plan.id, "plan_date": plan.plan_date, "items": items,
                "done_count": done, "total": len(items)}


# ---------------------------------------------------------------------------
# OKRs (D49)
# ---------------------------------------------------------------------------
def create_objective(db: DatabaseManager, project_id: str, title: str,
                     description: str = "", period: str = "") -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise PlanningError("An objective needs a title.")
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise PlanningError("Project not found.")
        o = Objective(id=str(uuid.uuid4()), project_id=project_id, title=title[:200],
                      description=description[:2000], period=period[:60])
        s.add(o)
        s.commit()
        return {"id": o.id, "title": o.title, "period": o.period, "key_results": []}


def add_key_result(db: DatabaseManager, objective_id: str, title: str,
                   target: float = 100.0) -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise PlanningError("A key result needs a title.")
    with db.get_session() as s:
        o = s.get(Objective, objective_id)
        if not o:
            raise PlanningError("Objective not found.")
        kr = KeyResult(id=str(uuid.uuid4()), objective_id=objective_id,
                       project_id=o.project_id, title=title[:200], target=target)
        s.add(kr)
        s.commit()
        return {"id": kr.id, "title": kr.title, "target": kr.target}


def link_feature_to_kr(db: DatabaseManager, key_result_id: str,
                       feature_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        kr = s.get(KeyResult, key_result_id)
        if not kr:
            raise PlanningError("Key result not found.")
        f = s.get(FeatureBacklog, feature_id)
        if not f or f.project_id != kr.project_id:
            raise PlanningError("Feature not found in this project.")
        existing = (s.query(KeyResultLink)
                    .filter(KeyResultLink.key_result_id == key_result_id,
                            KeyResultLink.feature_id == feature_id).first())
        if not existing:
            s.add(KeyResultLink(id=str(uuid.uuid4()), key_result_id=key_result_id,
                                feature_id=feature_id))
            s.commit()
    return kr_progress(db, key_result_id)


def kr_progress(db: DatabaseManager, key_result_id: str) -> Dict[str, Any]:
    """Progress weighted by Pareto impact — finishing a big thing moves it more."""
    with db.get_session() as s:
        kr = s.get(KeyResult, key_result_id)
        if not kr:
            raise PlanningError("Key result not found.")
        links = (s.query(KeyResultLink)
                 .filter(KeyResultLink.key_result_id == key_result_id).all())
        ids = [l.feature_id for l in links]
        if not ids:
            return {"id": kr.id, "title": kr.title, "percent": 0.0,
                    "linked": 0, "completed": 0}

        features = s.query(FeatureBacklog).filter(FeatureBacklog.id.in_(ids)).all()
        metas = {m.feature_id: m for m in
                 s.query(PlanningMeta).filter(PlanningMeta.feature_id.in_(ids)).all()}

        total_weight = sum(max(1, f.impact_score or 1) for f in features)
        done_weight = 0
        completed = 0
        for f in features:
            m = metas.get(f.id)
            is_done = (m and m.board_column == "done") or f.status == "completed"
            if is_done:
                done_weight += max(1, f.impact_score or 1)
                completed += 1

        return {
            "id": kr.id, "title": kr.title, "linked": len(features),
            "completed": completed,
            "percent": round(100.0 * done_weight / total_weight, 1) if total_weight else 0.0,
        }


def list_objectives(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        objectives = (s.query(Objective)
                      .filter(Objective.project_id == project_id).all())
        out = []
        for o in objectives:
            krs = s.query(KeyResult).filter(KeyResult.objective_id == o.id).all()
            kr_dicts = [kr_progress(db, kr.id) for kr in krs]
            percent = (round(sum(k["percent"] for k in kr_dicts) / len(kr_dicts), 1)
                       if kr_dicts else 0.0)
            out.append({"id": o.id, "title": o.title, "description": o.description,
                        "period": o.period, "key_results": kr_dicts,
                        "percent": percent})
        return out
