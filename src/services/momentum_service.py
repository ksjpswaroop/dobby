"""
Daily streak & momentum (100-Day Roadmap, Day 5).

Two decisions worth stating, because both look arbitrary otherwise:

**Where activity comes from.** The roadmap says "derive from the audit log",
but `AuditEntry` is only written for node create/update/verify — it has never
recorded idea captures, runs, or research, which are exactly the qualifying
actions the streak is supposed to reward. Rather than retrofit audit calls
across four services (and silently change what every existing audit consumer
sees), momentum reads the same derived feed the Activity Timeline already
builds. That feed *is* the record of qualifying activity.

**Where the day boundary comes from.** Timestamps are stored in UTC, but a
streak is a human, local-calendar concept: something done at 11:59pm and
something done at 12:01am are different days to the user and the same day to
UTC. The client passes its own UTC offset (the browser is the only component
that reliably knows it), and every boundary here is computed from that offset.
Passing no offset falls back to the server's own local timezone, which is
correct for the normal case where the backend runs on the same machine.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from src.db.schema import DatabaseManager
from src.services import timeline_service

SPARKLINE_DAYS = 14

# Everything the timeline emits counts as building except passive reads.
# Kept as a prefix list so a new `run_*`/`idea_*` event type is included by
# default rather than silently failing to count toward someone's streak.
QUALIFYING_PREFIXES = ("idea_", "feature_", "run_", "research_")


def _local_day(iso_timestamp: str, tz_offset_minutes: int) -> date:
    """The local calendar day an event falls on, given the client's offset."""
    dt = datetime.fromisoformat(iso_timestamp)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return (dt + timedelta(minutes=tz_offset_minutes)).date()


def _today_local(tz_offset_minutes: int) -> date:
    return (datetime.utcnow() + timedelta(minutes=tz_offset_minutes)).date()


def _qualifies(event_type: str) -> bool:
    return any(event_type.startswith(p) for p in QUALIFYING_PREFIXES)


def active_days(events: List[Dict[str, Any]], tz_offset_minutes: int) -> Set[date]:
    """Distinct local days with at least one qualifying action.

    A set, so several actions on one day count that day exactly once.
    """
    return {
        _local_day(e["timestamp"], tz_offset_minutes)
        for e in events
        if e.get("timestamp") and _qualifies(e.get("type", ""))
    }


def streak_length(days: Set[date], today: date) -> int:
    """Consecutive active days ending today, or yesterday if today is idle.

    The yesterday grace matters: at 9am your streak is not broken yet, you
    simply have not built today. Counting from yesterday keeps the number
    honest without punishing someone for opening the app before working.
    """
    if not days:
        return 0

    if today in days:
        cursor = today
    elif (today - timedelta(days=1)) in days:
        cursor = today - timedelta(days=1)
    else:
        return 0

    length = 0
    while cursor in days:
        length += 1
        cursor -= timedelta(days=1)
    return length


def sparkline(events: List[Dict[str, Any]], tz_offset_minutes: int,
              today: date, days: int = SPARKLINE_DAYS) -> List[Dict[str, Any]]:
    """Per-day qualifying-action counts, oldest first, gaps included as zero."""
    counts: Dict[date, int] = {}
    for e in events:
        if not e.get("timestamp") or not _qualifies(e.get("type", "")):
            continue
        d = _local_day(e["timestamp"], tz_offset_minutes)
        counts[d] = counts.get(d, 0) + 1

    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        out.append({"date": d.isoformat(), "count": counts.get(d, 0)})
    return out


def get_momentum(db: DatabaseManager, project_id: str,
                 tz_offset_minutes: Optional[int] = None) -> Dict[str, Any]:
    if tz_offset_minutes is None:
        # Server-local offset: correct when the backend runs on the user's
        # own machine, which is the local-first default.
        tz_offset_minutes = -int(
            (datetime.utcnow() - datetime.now()).total_seconds() // 60
        )

    # One bounded read; the timeline caps per-source fetches already.
    page = timeline_service.list_events(db, project_id, limit=1000)
    events = page["events"]

    today = _today_local(tz_offset_minutes)
    days = active_days(events, tz_offset_minutes)
    length = streak_length(days, today)

    return {
        "streak": length,
        "active_today": today in days,
        "longest_recent": _longest_recent(days, today),
        "total_active_days": len(days),
        "sparkline": sparkline(events, tz_offset_minutes, today),
        "tz_offset_minutes": tz_offset_minutes,
    }


def _longest_recent(days: Set[date], today: date, window: int = 90) -> int:
    """Longest consecutive run within the recent window — the number to beat."""
    recent = sorted(d for d in days if (today - d).days < window)
    if not recent:
        return 0
    best = run = 1
    for prev, cur in zip(recent, recent[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    return best
