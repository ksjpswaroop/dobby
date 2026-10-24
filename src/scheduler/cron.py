"""
Cron expression parsing and next-fire computation.

Written rather than taken from `croniter` deliberately: Dobby ships with no
runtime dependency beyond the local model, and a five-field cron parser is a
day's work, not a library's worth. Standard library only, timezone-aware.

Supported in each of the five fields (`minute hour day-of-month month day-of-week`):

    *            every value
    5            a single value
    1,3,5        a list
    1-5          an inclusive range
    */15         a step over the whole range
    1-30/5       a step over a range
    mon, jan     three-letter names (day-of-week, month)

Plus the usual shorthands: ``@hourly @daily @midnight @weekly @monthly @yearly``.

Day-of-week accepts 0 or 7 for Sunday. When *both* day-of-month and day-of-week
are restricted, cron fires when **either** matches — the historical Vixie-cron
behaviour, which surprises people but is what every other implementation does,
so matching it is less surprising than not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Look no further ahead than this when searching for the next fire. Four years
# covers every schedule that will ever fire (including Feb 29) and bounds an
# impossible expression like "Feb 30" to a fast, definite "never".
MAX_SEARCH_DAYS = 366 * 4

_NAMES_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_NAMES_MONTH = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

SHORTHAND = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

# (low, high) per field, in cron order.
_BOUNDS: List[Tuple[int, int]] = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
_FIELD_NAMES = ["minute", "hour", "day-of-month", "month", "day-of-week"]


class CronError(ValueError):
    """An invalid cron expression. The message is shown to the user."""


@dataclass(frozen=True)
class CronSchedule:
    minutes: Set[int]
    hours: Set[int]
    days: Set[int]
    months: Set[int]
    weekdays: Set[int]
    # Whether the original expression restricted these, for the either/or rule.
    dom_restricted: bool
    dow_restricted: bool
    expression: str

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minutes or dt.hour not in self.hours:
            return False
        if dt.month not in self.months:
            return False
        # Python: Monday=0..Sunday=6. Cron: Sunday=0..Saturday=6.
        dow = (dt.weekday() + 1) % 7
        dom_ok = dt.day in self.days
        dow_ok = dow in self.weekdays
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok


def _parse_field(text: str, index: int) -> Tuple[Set[int], bool]:
    """Expand one cron field. Returns (values, was_restricted)."""
    low, high = _BOUNDS[index]
    names = _NAMES_DOW if index == 4 else (_NAMES_MONTH if index == 3 else {})
    field = text.strip().lower()
    if not field:
        raise CronError(f"The {_FIELD_NAMES[index]} field is empty.")

    restricted = field != "*"
    values: Set[int] = set()

    for part in field.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"Empty entry in the {_FIELD_NAMES[index]} field.")

        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(
                    f"Step must be a positive whole number in the "
                    f"{_FIELD_NAMES[index]} field, got {step_text!r}."
                )
            step = int(step_text)
            part = part or "*"

        if part == "*":
            start, end = low, high
        elif "-" in part.lstrip("-"):
            a, _, b = part.partition("-")
            start, end = _value(a, names, index), _value(b, names, index)
            if start > end:
                raise CronError(
                    f"Range {part!r} runs backwards in the {_FIELD_NAMES[index]} field."
                )
        else:
            start = end = _value(part, names, index)

        for v in range(start, end + 1, step):
            # Cron allows 7 for Sunday; normalise it onto 0.
            values.add(0 if index == 4 and v == 7 else v)

    return values, restricted


def _value(token: str, names: Dict[str, int], index: int) -> int:
    low, high = _BOUNDS[index]
    token = token.strip()
    if token[:3] in names:
        return names[token[:3]]
    if not re.fullmatch(r"\d+", token):
        raise CronError(f"{token!r} is not valid in the {_FIELD_NAMES[index]} field.")
    v = int(token)
    # 7 == Sunday is legal input even though the bound is 6.
    ceiling = 7 if index == 4 else high
    if not (low <= v <= ceiling):
        raise CronError(
            f"{v} is out of range for the {_FIELD_NAMES[index]} field "
            f"({low}-{high})."
        )
    return v


def parse(expression: str) -> CronSchedule:
    """Parse a cron expression or shorthand into a schedule."""
    raw = (expression or "").strip()
    if not raw:
        raise CronError("Enter a schedule, for example `0 9 * * 1-5`.")

    expr = SHORTHAND.get(raw.lower(), raw)
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"A cron expression needs 5 fields "
            f"(minute hour day-of-month month day-of-week); got {len(fields)}."
        )

    parsed = [_parse_field(f, i) for i, f in enumerate(fields)]
    for (values, _), name in zip(parsed, _FIELD_NAMES):
        if not values:
            raise CronError(f"The {name} field matches nothing.")

    return CronSchedule(
        minutes=parsed[0][0], hours=parsed[1][0], days=parsed[2][0],
        months=parsed[3][0], weekdays=parsed[4][0],
        dom_restricted=parsed[2][1], dow_restricted=parsed[4][1],
        expression=raw,
    )


def get_timezone(name: Optional[str]) -> timezone | ZoneInfo:
    """Resolve a timezone name, falling back to UTC rather than failing."""
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return timezone.utc


def next_fire(expression: str, after: Optional[datetime] = None,
              tz_name: Optional[str] = None) -> Optional[datetime]:
    """The first firing time strictly after `after`, as an aware UTC datetime.

    The schedule is evaluated in the automation's own timezone — "every weekday
    at 9am" has to mean 9am where the user is, not 9am UTC — then converted back
    to UTC for storage, so everything downstream compares like with like.

    Returns None when the expression can never fire (e.g. `0 0 30 2 *`).
    """
    schedule = parse(expression)
    tz = get_timezone(tz_name)

    base = after or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    # Step from the next whole minute; cron has minute resolution.
    local = base.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)

    limit = local + timedelta(days=MAX_SEARCH_DAYS)
    while local < limit:
        if not (local.month in schedule.months and local.day in schedule.days
                or (schedule.dom_restricted and schedule.dow_restricted
                    and local.month in schedule.months)):
            # Whole day cannot match — skip to the next midnight rather than
            # walking 1,440 minutes of it.
            if local.month not in schedule.months or not _day_possible(schedule, local):
                local = (local + timedelta(days=1)).replace(hour=0, minute=0)
                continue
        if schedule.matches(local):
            return local.astimezone(timezone.utc)
        local += timedelta(minutes=1)
    return None


def _day_possible(schedule: CronSchedule, dt: datetime) -> bool:
    dow = (dt.weekday() + 1) % 7
    dom_ok, dow_ok = dt.day in schedule.days, dow in schedule.weekdays
    if schedule.dom_restricted and schedule.dow_restricted:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def describe(expression: str, tz_name: Optional[str] = None) -> str:
    """A short human reading of a schedule, for confirmation in the UI."""
    raw = (expression or "").strip().lower()
    if raw in SHORTHAND:
        return {
            "@hourly": "Every hour", "@daily": "Every day at midnight",
            "@midnight": "Every day at midnight", "@weekly": "Every Sunday",
            "@monthly": "On the 1st of every month",
            "@yearly": "Every 1 January", "@annually": "Every 1 January",
        }[raw]
    try:
        s = parse(expression)
    except CronError:
        return expression

    when = ("every minute" if len(s.minutes) == 60 and len(s.hours) == 24
            else f"{len(s.minutes) * len(s.hours)} times a day"
            if len(s.minutes) > 1 or len(s.hours) > 1
            else f"at {next(iter(s.hours)):02d}:{next(iter(s.minutes)):02d}")
    days = "every day"
    if s.dow_restricted:
        names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        days = "on " + ", ".join(names[d] for d in sorted(s.weekdays))
    elif s.dom_restricted:
        days = "on day " + ", ".join(str(d) for d in sorted(s.days))
    suffix = f" ({tz_name})" if tz_name else ""
    return f"{when.capitalize()}, {days}{suffix}"
