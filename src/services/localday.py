"""
Turning UTC timestamps into the user's calendar day.

Everything is stored in UTC, but every day-shaped question — "what did I do
today?", "how long is my streak?", "what goes on today's journal page?" — is
asked about the *user's* day. Comparing a UTC timestamp against a local date
works fine in London and quietly breaks everywhere else: at 19:00 in New York
it is already tomorrow in UTC, so an evening's work lands on the wrong day, or
on no day at all.

Three services independently need this, so the conversion lives in one place
rather than being re-derived (and re-broken) in each.

The default offset is *this machine's*, because in a local-first app the
backend runs on the user's own computer. A client that knows better — the
browser, which has the real offset — passes it explicitly and wins.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple


def resolve_offset(tz_offset_minutes: Optional[int] = None) -> int:
    """The client's offset from UTC, falling back to this machine's."""
    if tz_offset_minutes is not None:
        return int(tz_offset_minutes)
    return -int((datetime.utcnow() - datetime.now()).total_seconds() // 60)


def to_naive_utc(value) -> Optional[datetime]:
    """Accept a datetime or ISO string; return naive UTC, or None if unusable."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def local_day(value, tz_offset_minutes: Optional[int] = None) -> Optional[date]:
    """The local calendar day a UTC-stamped moment falls on."""
    dt = to_naive_utc(value)
    if dt is None:
        return None
    return (dt + timedelta(minutes=resolve_offset(tz_offset_minutes))).date()


def today_local(tz_offset_minutes: Optional[int] = None) -> date:
    return (datetime.utcnow()
            + timedelta(minutes=resolve_offset(tz_offset_minutes))).date()


def utc_window(day: date,
               tz_offset_minutes: Optional[int] = None) -> Tuple[datetime, datetime]:
    """The half-open UTC range [start, end) covering one local day.

    Returned as naive UTC so it can be compared directly against the naive
    columns the models store.
    """
    offset = timedelta(minutes=resolve_offset(tz_offset_minutes))
    start_local = datetime.combine(day, datetime.min.time())
    start_utc = start_local - offset
    return start_utc, start_utc + timedelta(days=1)
