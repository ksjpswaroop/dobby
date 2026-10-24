"""
Delivery analytics and the weekly ritual (100-Day Roadmap, Days 48 & 50).

Everything here is computed from `FeatureStatusChange`, which is append-only.
That is the whole reason the board records every move: velocity, throughput,
and cycle time are questions about *when* work moved, and current state cannot
answer any of them.

Cycle time is measured from the first move into `in_progress` to the first
move into `done`. Work that bounced back out of Done and returned counts its
*first* completion, because that is when it was first deliverable — counting
the last one would let a late typo fix inflate a month-old cycle time.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.db.planning_models import (
    BOARD_COLUMNS, Blocker, FeatureStatusChange, PlanningMeta, Sprint,
)
from src.db.schema import DatabaseManager, FeatureBacklog


def _week_start(d: datetime) -> str:
    return (d - timedelta(days=d.weekday())).date().isoformat()


def throughput(db: DatabaseManager, project_id: str, weeks: int = 12) -> List[Dict[str, Any]]:
    """Items completed per week, with zero-filled gaps."""
    since = datetime.utcnow() - timedelta(weeks=weeks)
    with db.get_session() as s:
        rows = (s.query(FeatureStatusChange)
                .filter(FeatureStatusChange.project_id == project_id,
                        FeatureStatusChange.to_column == "done",
                        FeatureStatusChange.created_at >= since).all())

    counted: Dict[str, Dict[str, float]] = defaultdict(lambda: {"items": 0, "estimate": 0.0})
    seen_features = set()
    for r in sorted(rows, key=lambda x: x.created_at or datetime.utcnow()):
        if r.feature_id in seen_features:
            continue  # only the first completion counts
        seen_features.add(r.feature_id)
        wk = _week_start(r.created_at or datetime.utcnow())
        counted[wk]["items"] += 1
        counted[wk]["estimate"] += r.estimate or 0.0

    today = datetime.utcnow()
    out = []
    for i in range(weeks - 1, -1, -1):
        wk = _week_start(today - timedelta(weeks=i))
        c = counted.get(wk, {"items": 0, "estimate": 0.0})
        out.append({"week": wk, "items": int(c["items"]),
                    "estimate": round(c["estimate"], 2)})
    return out


def cycle_times(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        rows = (s.query(FeatureStatusChange)
                .filter(FeatureStatusChange.project_id == project_id)
                .order_by(FeatureStatusChange.created_at).all())
        titles = {f.id: f.title for f in s.query(FeatureBacklog)
                  .filter(FeatureBacklog.project_id == project_id).all()}

    started: Dict[str, datetime] = {}
    finished: Dict[str, datetime] = {}
    for r in rows:
        when = r.created_at or datetime.utcnow()
        if r.to_column == "in_progress" and r.feature_id not in started:
            started[r.feature_id] = when
        if r.to_column == "done" and r.feature_id not in finished:
            finished[r.feature_id] = when

    per_item = []
    for fid, end in finished.items():
        start = started.get(fid)
        if not start or end < start:
            continue
        hours = (end - start).total_seconds() / 3600.0
        per_item.append({"feature_id": fid, "title": titles.get(fid, ""),
                         "hours": round(hours, 1), "days": round(hours / 24.0, 2)})

    per_item.sort(key=lambda x: -x["hours"])
    values = [p["hours"] for p in per_item]
    values_sorted = sorted(values)
    median = (values_sorted[len(values_sorted) // 2] if values_sorted else 0.0)

    return {
        "count": len(per_item),
        "average_hours": round(sum(values) / len(values), 1) if values else 0.0,
        "median_hours": round(median, 1),
        "slowest": per_item[:5],
    }


def velocity(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    """Completed estimate per closed or active sprint."""
    with db.get_session() as s:
        sprints = (s.query(Sprint).filter(Sprint.project_id == project_id)
                   .order_by(Sprint.starts_on).all())
        out = []
        for sp in sprints:
            metas = s.query(PlanningMeta).filter(PlanningMeta.sprint_id == sp.id).all()
            committed = sum(m.estimate or 0.0 for m in metas)
            completed = sum(m.estimate or 0.0 for m in metas if m.board_column == "done")
            out.append({
                "sprint_id": sp.id, "name": sp.name, "state": sp.state,
                "committed": round(committed, 2), "completed": round(completed, 2),
                "capacity": sp.capacity,
                "hit_rate": round(100.0 * completed / committed, 1) if committed else 0.0,
            })
        return out


def cumulative_flow(db: DatabaseManager, project_id: str,
                    days: int = 30) -> List[Dict[str, Any]]:
    """How many items sat in each column at the end of each day."""
    with db.get_session() as s:
        rows = (s.query(FeatureStatusChange)
                .filter(FeatureStatusChange.project_id == project_id)
                .order_by(FeatureStatusChange.created_at).all())

    today = datetime.utcnow().date()
    start = today - timedelta(days=days - 1)

    state: Dict[str, str] = {}
    by_day: Dict[str, Dict[str, str]] = {}
    for r in rows:
        d = (r.created_at or datetime.utcnow()).date()
        state[r.feature_id] = r.to_column
        if d >= start:
            by_day[d.isoformat()] = dict(state)

    out = []
    last = dict(state) if not by_day else None
    running: Dict[str, str] = {}
    # Replay forward so a day with no changes inherits the previous day.
    for r in rows:
        d = (r.created_at or datetime.utcnow()).date()
        if d < start:
            running[r.feature_id] = r.to_column

    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        if d in by_day:
            running = by_day[d]
        counts = {c: 0 for c in BOARD_COLUMNS}
        for col in running.values():
            if col in counts:
                counts[col] += 1
        out.append({"date": d, **counts})
    return out


def summary(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    tp = throughput(db, project_id, weeks=12)
    recent = [w["items"] for w in tp[-4:]]
    return {
        "throughput": tp,
        "velocity": velocity(db, project_id),
        "cycle_time": cycle_times(db, project_id),
        "cumulative_flow": cumulative_flow(db, project_id),
        "avg_items_per_week": round(sum(recent) / len(recent), 1) if recent else 0.0,
    }


# ---------------------------------------------------------------------------
# Weekly ritual (D48)
# ---------------------------------------------------------------------------
def weekly_review(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """Close out last week, see what carried over, plan against real velocity."""
    now = datetime.utcnow()
    this_week = now - timedelta(days=now.weekday())
    last_week = this_week - timedelta(weeks=1)

    with db.get_session() as s:
        changes = (s.query(FeatureStatusChange)
                   .filter(FeatureStatusChange.project_id == project_id,
                           FeatureStatusChange.created_at >= last_week).all())
        titles = {f.id: f.title for f in s.query(FeatureBacklog)
                  .filter(FeatureBacklog.project_id == project_id).all()}

        completed_last_week = []
        seen = set()
        for r in sorted(changes, key=lambda x: x.created_at or now):
            if (r.to_column == "done" and r.created_at
                    and last_week <= r.created_at < this_week
                    and r.feature_id not in seen):
                seen.add(r.feature_id)
                completed_last_week.append({"feature_id": r.feature_id,
                                            "title": titles.get(r.feature_id, ""),
                                            "estimate": r.estimate or 0.0})

        # Carryover: still in progress, and it started before this week began.
        metas = s.query(PlanningMeta).filter(PlanningMeta.project_id == project_id).all()
        carryover = [{"feature_id": m.feature_id, "title": titles.get(m.feature_id, ""),
                      "started_at": m.started_at.isoformat() if m.started_at else None,
                      "days_in_progress": round((now - m.started_at).days, 1)
                      if m.started_at else 0}
                     for m in metas
                     if m.board_column == "in_progress" and m.started_at
                     and m.started_at < this_week]
        carryover.sort(key=lambda c: -c["days_in_progress"])

        blockers = s.query(Blocker).filter(Blocker.project_id == project_id).all()
        long_blocked = [{"feature_id": b.feature_id,
                         "title": titles.get(b.feature_id, ""),
                         "blocked_by": titles.get(b.blocked_by_id, ""),
                         "days": (now - b.created_at).days if b.created_at else 0}
                        for b in blockers if b.created_at
                        and (now - b.created_at).days >= 7]
        long_blocked.sort(key=lambda x: -x["days"])

    tp = throughput(db, project_id, weeks=8)
    recent = [w["items"] for w in tp[-4:] if w["items"] or True]
    suggested_capacity = round(sum(recent) / len(recent), 1) if recent else 0.0

    from src.services.planning_service import ready_features

    ready = ready_features(db, project_id)

    return {
        "week_of": this_week.date().isoformat(),
        "completed_last_week": completed_last_week,
        "completed_count": len(completed_last_week),
        "carryover": carryover,
        "long_blocked": long_blocked,
        "suggested_capacity": suggested_capacity,
        "capacity_basis": "Average items completed per week over the last 4 weeks.",
        "ready_next": ready[:10],
    }
