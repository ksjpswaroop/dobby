"""
One place that converts effort between points and minutes.

This module exists because the planner and the scheduler disagreed.
`propose_daily_plan` counted *points* while the time-block scheduler counted
*minutes*, so a capacity of 8 admitted a single 7-point item and the block
cap then trimmed it to 2.5 hours — leaving four hours of the day empty at
29% utilisation. Two components measuring the same thing in different units
will always drift; the fix is one conversion, in one place, that both import.

**Minutes are canonical.** Points are a user-facing estimate that seeds from
the Pareto effort score, and they are a proxy for time whether or not anyone
admits it. Everything that schedules, sums, or subtracts works in minutes.

`MINUTES_PER_POINT` is deliberately generous. A planner that assumes
best-case throughput produces days nobody finishes, and the failure is
asymmetric: over-estimating costs you an early finish, under-estimating costs
you the trust you had in the plan.
"""

from __future__ import annotations

from typing import Optional

# The default conversion. Overridable in settings, and later learnable from
# real cycle-time data — see delivery_analytics.
DEFAULT_MINUTES_PER_POINT = 45

# Bounds on a single sitting, not on a task. A task can be many blocks.
DEFAULT_MIN_BLOCK_MINUTES = 30
DEFAULT_MAX_BLOCK_MINUTES = 150


def minutes_per_point() -> int:
    from src.settings import get_settings

    value = getattr(get_settings(), "minutes_per_point", None)
    try:
        return max(5, min(int(value), 480)) if value else DEFAULT_MINUTES_PER_POINT
    except (TypeError, ValueError):
        return DEFAULT_MINUTES_PER_POINT


def points_to_minutes(points: Optional[float]) -> int:
    """Estimate in points to an amount of real time."""
    try:
        p = float(points if points is not None else 1.0)
    except (TypeError, ValueError):
        p = 1.0
    return max(0, int(round(p * minutes_per_point())))


def minutes_to_points(minutes: Optional[float]) -> float:
    try:
        m = float(minutes or 0)
    except (TypeError, ValueError):
        m = 0.0
    return round(m / minutes_per_point(), 2)


def hours(minutes: Optional[float]) -> float:
    try:
        return round(float(minutes or 0) / 60.0, 1)
    except (TypeError, ValueError):
        return 0.0


def humanise(minutes: Optional[float]) -> str:
    """'2h 15m' — used anywhere a number of minutes is shown to a person."""
    try:
        total = int(round(float(minutes or 0)))
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        return "0m"
    h, m = divmod(total, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"
