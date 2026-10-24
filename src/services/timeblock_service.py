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

from src.services import effort

# Kept as a module attribute because callers and tests read it; the value now
# lives in `services/effort` so the planner and the scheduler cannot drift.
MINUTES_PER_POINT = effort.DEFAULT_MINUTES_PER_POINT

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


def _minutes_for(item: Dict[str, Any], shape: Dict[str, Any]) -> tuple:
    """Block length, and how much of the item is left after it.

    Prefers `remaining_minutes` over the raw estimate, so an item that has
    already had two hours today only asks for what is left. Using the full
    estimate every day is why a capped block used to repeat forever with the
    work never visibly shrinking.

    Capping silently would be the dishonest move: a 7-point item shown as a
    150-minute block reads as finishable today when the estimate says it is
    most of a week. The caller surfaces the difference.
    """
    wanted = item.get("remaining_minutes")
    if wanted is None:
        wanted = effort.points_to_minutes(item.get("estimate"))
    wanted = max(0, int(wanted))

    minutes = max(int(shape["min_block_minutes"]),
                  min(wanted, int(shape["max_block_minutes"])))
    # The floor and "never over-book" conflict for a nearly-finished item, and
    # the floor loses: inflating 8 minutes of remaining work into a 30-minute
    # block books 22 minutes of work that does not exist, and does it on the
    # day someone is trying to clear the last of something. A short block is
    # honest; a padded one quietly makes the day too full.
    minutes = min(minutes, wanted) if wanted else minutes
    return minutes, wanted > minutes, wanted


def _why(item: Dict[str, Any], minutes: int, wanted: int, capped: bool,
         default: str) -> str:
    """The sentence under a block. Says what is left, not what was estimated."""
    spent = int(item.get("spent_minutes") or 0)
    if not capped:
        if spent:
            return f"{effort.humanise(spent)} already in — this should finish it."
        return default
    left = max(0, wanted - minutes)
    if spent:
        return (f"{effort.humanise(spent)} in, {effort.humanise(wanted)} left. "
                f"This block leaves {effort.humanise(left)}.")
    return (f"A first block — {effort.humanise(wanted)} in total, "
            f"leaving {effort.humanise(left)} after this.")


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
        minutes, capped, wanted = _minutes_for(item, shape)
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
                "remaining_minutes": wanted,
                "spent_minutes": item.get("spent_minutes", 0),
                "leaves_remaining": max(0, wanted - minutes),
                "why": _why(item, minutes, wanted, capped,
                            "Highest-value work, placed while your focus is best."),
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
        minutes, capped, wanted = _minutes_for(item, shape)
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
                "remaining_minutes": wanted,
                "spent_minutes": item.get("spent_minutes", 0),
                "leaves_remaining": max(0, wanted - minutes),
                "why": _why(item, minutes, wanted, capped,
                            "Scheduled after the deep-work window."),
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
             capacity: Optional[float] = None, plan_date: Optional[str] = None,
             overrides: Optional[Dict[str, Any]] = None,
             capacity_minutes: Optional[int] = None) -> Dict[str, Any]:
    """What to do today *and* when — one call.

    Capacity defaults to the working day itself rather than a number someone
    guessed: the planner and the scheduler now share a unit, so "what fits"
    can simply be "what fits between start and end, minus lunch".
    """
    from src.services import planning_service

    shape = day_shape(overrides)
    if capacity_minutes is None and capacity is None:
        capacity_minutes = _workable_minutes(shape)

    proposal = planning_service.propose_daily_plan(
        db, project_id, capacity, capacity_minutes,
        max_per_item_minutes=int(shape["max_block_minutes"]))
    schedule = build_schedule(proposal["proposed"], plan_date, overrides)
    schedule["ready_count"] = proposal["ready_count"]
    schedule["capacity_minutes"] = proposal["capacity_minutes"]
    schedule["capacity_human"] = proposal["capacity_human"]
    # Two different ways work can miss the day, and the caller should see
    # both: the planner never offered it, or the clock had no room.
    schedule["not_today"] = proposal.get("not_today", [])
    schedule["fits"] = not schedule["unscheduled"] and not schedule["not_today"]
    return schedule


def _workable_minutes(shape: Dict[str, Any]) -> int:
    """Minutes actually available: the day, minus lunch, minus buffers.

    Handing the planner the raw day length would over-fill it by exactly the
    time the scheduler then spends on breaks and gaps.
    """
    day = _parse_hhmm(shape["end"], "end")
    start = _parse_hhmm(shape["start"], "start")
    lunch_start = _parse_hhmm(shape["lunch_start"], "lunch_start")
    lunch_end = _parse_hhmm(shape["lunch_end"], "lunch_end")

    def mins(t):
        return t.hour * 60 + t.minute

    total = mins(day) - mins(start)
    total -= max(0, mins(lunch_end) - mins(lunch_start))
    # Roughly one buffer per two-hour block; better to under-promise.
    total -= int(shape["buffer_minutes"]) * max(1, total // 120)
    return max(0, total)


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
