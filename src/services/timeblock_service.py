"""
Time-blocked planning (Work Graph, step 4).

`propose_daily_plan` already answers *what* to do today: the highest-value
ready work that fits your capacity, with blocked items excluded. This answers
*when*, by laying those items onto the clock.

Three rules, each of which is the difference between a plan you follow and
one you delete:

**Deep work goes where your energy is, not where there is room.** Blocks are
placed highest-value-first into the *deep-work window* before anything else
is scheduled. A plan that puts the hardest thing at 4pm because the morning
filled up with small tasks is a plan that quietly fails every day.

**Every block gets a buffer.** Back-to-back blocks assume tasks end exactly
when predicted, which they never do. A small gap after each one absorbs the
overrun instead of cascading it through the whole afternoon.

**A plan that does not fit says so.** Rather than silently truncating or
compressing, anything that will not fit the day is returned as `unscheduled`
with the reason. Being told "these two will not fit" is useful; discovering
it at 6pm is not.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager

logger = structlog.get_logger()

# Minutes of real work one estimate point represents. Deliberately generous:
# a planner that assumes best-case throughput produces days nobody finishes.
MINUTES_PER_POINT = 45

DEFAULT_DAY = {
    "start": "09:00",
    "end": "17:30",
    "deep_work_start": "09:00",
    "deep_work_end": "12:30",
    "lunch_start": "12:30",
    "lunch_end": "13:30",
    "buffer_minutes": 15,
    "min_block_minutes": 30,
    "max_block_minutes": 150,
}

BLOCK_KINDS = ("deep_work", "collaboration", "admin", "break")


class TimeblockError(Exception):
    pass


def _parse_hhmm(value: str, field: str) -> time:
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        raise TimeblockError(f"{field} must look like 09:00.")


def day_shape(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The user's working day, with any overrides validated."""
    shape = dict(DEFAULT_DAY)
    shape.update({k: v for k, v in (overrides or {}).items() if v is not None})

    start = _parse_hhmm(shape["start"], "start")
    end = _parse_hhmm(shape["end"], "end")
    if end <= start:
        raise TimeblockError("The day has to end after it starts.")

    deep_start = _parse_hhmm(shape["deep_work_start"], "deep_work_start")
    deep_end = _parse_hhmm(shape["deep_work_end"], "deep_work_end")
    if deep_end <= deep_start:
        raise TimeblockError("The deep-work window has to end after it starts.")
    if deep_start < start or deep_end > end:
        raise TimeblockError("The deep-work window has to sit inside the working day.")

    try:
        buffer_minutes = int(shape["buffer_minutes"])
    except (TypeError, ValueError):
        raise TimeblockError("buffer_minutes must be a number.")
    if buffer_minutes < 0 or buffer_minutes > 60:
        raise TimeblockError("A buffer between 0 and 60 minutes is sensible.")

    shape["buffer_minutes"] = buffer_minutes
    return shape


def _minutes_for(estimate: Optional[float], shape: Dict[str, Any]) -> tuple:
    """Block length, and whether the estimate had to be capped.

    Capping silently would be the dishonest move: a 7-point item shown as a
    150-minute block reads as something you can finish today, when the
    estimate says it is most of a week. The caller surfaces the difference.
    """
    points = float(estimate or 1.0)
    wanted = int(round(points * MINUTES_PER_POINT))
    minutes = max(int(shape["min_block_minutes"]),
                  min(wanted, int(shape["max_block_minutes"])))
    return minutes, wanted > minutes, wanted


def _to_dt(day: date, t: time) -> datetime:
    return datetime.combine(day, t)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


class _Cursor:
    """Walks the day, skipping lunch and respecting the end of the day."""

    def __init__(self, day: date, shape: Dict[str, Any]):
        self.day = day
        self.shape = shape
        self.at = _to_dt(day, _parse_hhmm(shape["start"], "start"))
        self.end = _to_dt(day, _parse_hhmm(shape["end"], "end"))
        self.lunch_start = _to_dt(day, _parse_hhmm(shape["lunch_start"], "lunch_start"))
        self.lunch_end = _to_dt(day, _parse_hhmm(shape["lunch_end"], "lunch_end"))

    def _skip_lunch(self, start: datetime, minutes: int) -> datetime:
        finish = start + timedelta(minutes=minutes)
        # Anything that would run through lunch starts after it instead of
        # eating it — a plan that books over lunch is one people abandon.
        if start < self.lunch_end and finish > self.lunch_start:
            return self.lunch_end
        return start

    def place(self, minutes: int, not_before: Optional[datetime] = None,
              not_after: Optional[datetime] = None) -> Optional[tuple]:
        start = max(self.at, not_before) if not_before else self.at
        start = self._skip_lunch(start, minutes)
        finish = start + timedelta(minutes=minutes)

        if finish > self.end:
            return None
        if not_after and finish > not_after:
            return None

        self.at = finish + timedelta(minutes=self.shape["buffer_minutes"])
        return start, finish


def build_schedule(items: List[Dict[str, Any]], plan_date: Optional[str] = None,
                   overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lay planned items onto the clock, deep work first.

    `items` is what `propose_daily_plan` returns: each needs a title and an
    estimate; `pareto_score` orders them if present.
    """
    shape = day_shape(overrides)
    day = (datetime.fromisoformat(plan_date).date() if plan_date
           else datetime.now().date())

    ranked = sorted(items, key=lambda i: -(i.get("pareto_score") or 0))
    cursor = _Cursor(day, shape)

    deep_end = _to_dt(day, _parse_hhmm(shape["deep_work_end"], "deep_work_end"))

    blocks: List[Dict[str, Any]] = []
    unscheduled: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []

    # Pass one: the most valuable work into the deep-work window.
    for item in ranked:
        minutes, capped, wanted = _minutes_for(item.get("estimate"), shape)
        placed = cursor.place(minutes, not_after=deep_end)
        if placed:
            start, finish = placed
            blocks.append({
                "feature_id": item.get("feature_id"),
                "title": item.get("title", "Untitled"),
                "kind": "deep_work",
                "start": _fmt(start), "end": _fmt(finish),
                "minutes": minutes,
                "estimate": item.get("estimate"),
                "partial": capped,
                "estimated_minutes": wanted,
                "why": ("Highest-value work, placed while your focus is best."
                        if not capped else
                        f"A first block on this — the estimate is about "
                        f"{round(wanted / 60, 1)}h in total."),
            })
        else:
            deferred.append(item)

    # Lunch is a block so the day reads honestly rather than showing a gap.
    blocks.append({
        "feature_id": None, "title": "Lunch", "kind": "break",
        "start": shape["lunch_start"], "end": shape["lunch_end"],
        "minutes": int((_to_dt(day, _parse_hhmm(shape["lunch_end"], "lunch_end"))
                        - _to_dt(day, _parse_hhmm(shape["lunch_start"], "lunch_start")))
                       .total_seconds() // 60),
        "estimate": None, "why": "Protected.",
    })

    # Pass two: everything else into the rest of the day.
    for item in deferred:
        minutes, capped, wanted = _minutes_for(item.get("estimate"), shape)
        placed = cursor.place(minutes)
        if placed:
            start, finish = placed
            blocks.append({
                "feature_id": item.get("feature_id"),
                "title": item.get("title", "Untitled"),
                "kind": "admin",
                "start": _fmt(start), "end": _fmt(finish),
                "minutes": minutes,
                "estimate": item.get("estimate"),
                "partial": capped,
                "estimated_minutes": wanted,
                "why": ("Scheduled after the deep-work window."
                        if not capped else
                        f"A first block on this — about {round(wanted / 60, 1)}h in total."),
            })
        else:
            unscheduled.append({
                "feature_id": item.get("feature_id"),
                "title": item.get("title", "Untitled"),
                "estimate": item.get("estimate"),
                "reason": f"Needs {minutes} minutes and the day is full.",
            })

    blocks.sort(key=lambda b: b["start"])

    working_minutes = sum(b["minutes"] for b in blocks if b["kind"] != "break")
    day_minutes = int((_to_dt(day, _parse_hhmm(shape["end"], "end"))
                       - _to_dt(day, _parse_hhmm(shape["start"], "start")))
                      .total_seconds() // 60)

    return {
        "date": day.isoformat(),
        "blocks": blocks,
        "unscheduled": unscheduled,
        "shape": shape,
        "scheduled_minutes": working_minutes,
        "day_minutes": day_minutes,
        "utilisation": round(100.0 * working_minutes / day_minutes, 1) if day_minutes else 0.0,
        "minutes_per_point": MINUTES_PER_POINT,
        "partial_blocks": sum(1 for b in blocks if b.get("partial")),
        # Stated rather than implied: the caller should know the plan is not
        # complete, and why.
        "fits": not unscheduled,
    }


def plan_day(db: DatabaseManager, project_id: str,
             capacity: float = 6.0, plan_date: Optional[str] = None,
             overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What to do today *and* when — one call.

    Capacity defaults higher than the untimed planner's, because a day laid
    out on the clock can hold more than a list someone eyeballs.
    """
    from src.services import planning_service

    proposal = planning_service.propose_daily_plan(db, project_id, capacity)
    schedule = build_schedule(proposal["proposed"], plan_date, overrides)
    schedule["ready_count"] = proposal["ready_count"]
    schedule["capacity"] = capacity
    return schedule


def commit_day(db: DatabaseManager, project_id: str, plan_date: str,
               blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist a time-blocked plan through the existing daily-plan store."""
    from src.services import planning_service

    items = [{
        "feature_id": b.get("feature_id"),
        "title": b.get("title", ""),
        "estimate": b.get("estimate") or 0,
        "done": bool(b.get("done")),
        # The times travel with the item, so a committed plan reads back as a
        # schedule rather than an unordered list.
        "start": b.get("start"),
        "end": b.get("end"),
        "kind": b.get("kind", "admin"),
    } for b in blocks if b.get("kind") != "break"]

    return planning_service.commit_daily_plan(db, project_id, plan_date, items)
