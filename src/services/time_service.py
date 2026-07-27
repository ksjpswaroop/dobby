"""
Recording and summing time actually spent.

Three rules make the numbers trustworthy enough to schedule against:

**One running timer per project.** Starting a second stops the first rather
than leaving two clocks running, because a log where two things were worked
on simultaneously is a log nobody believes.

**Running state is derived, not stored.** "Am I tracking?" is a query for an
entry with no `ended_at`, so there is no flag that can disagree with the log
— the same rule the board's blocked column follows.

**A stopped entry is immutable.** Correcting history is how a time log
becomes fiction; a wrong entry is deleted and re-logged, which leaves the
deletion visible in the totals rather than silently altering them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager, FeatureBacklog, Project
from src.db.time_models import TIME_SOURCES, TimeEntry
from src.services import effort

logger = structlog.get_logger()

# A timer left running overnight is someone who forgot, not a 14-hour sitting.
# Capped rather than discarded: the work did happen, the duration is fiction.
MAX_SESSION_MINUTES = 8 * 60


class TimeError(Exception):
    pass


def _entry_dict(e: TimeEntry) -> Dict[str, Any]:
    running = e.ended_at is None
    live_minutes = e.minutes or 0
    if running:
        live_minutes = int((datetime.utcnow() - e.started_at).total_seconds() // 60)
    return {
        "id": e.id, "project_id": e.project_id, "feature_id": e.feature_id,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "ended_at": e.ended_at.isoformat() if e.ended_at else None,
        "running": running,
        "minutes": live_minutes,
        "human": effort.humanise(live_minutes),
        "source": e.source, "note": e.note,
    }


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------
def running(db: DatabaseManager, project_id: str) -> Optional[Dict[str, Any]]:
    """The entry with no end, if there is one."""
    with db.get_session() as s:
        e = (s.query(TimeEntry)
             .filter(TimeEntry.project_id == project_id,
                     TimeEntry.ended_at.is_(None))
             .order_by(TimeEntry.started_at.desc()).first())
        return _entry_dict(e) if e else None


def start(db: DatabaseManager, project_id: str,
          feature_id: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    """Start the clock, stopping whatever was already running."""
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise TimeError("Project not found.")
        if feature_id and not s.get(FeatureBacklog, feature_id):
            raise TimeError("Feature not found.")

    # Two clocks running at once produces a log nobody believes.
    previous = running(db, project_id)
    if previous:
        stop(db, project_id)

    with db.get_session() as s:
        entry = TimeEntry(
            id=str(uuid.uuid4()), project_id=project_id, feature_id=feature_id,
            started_at=datetime.utcnow(), source="timer", note=note[:500],
        )
        s.add(entry)
        s.commit()
        out = _entry_dict(entry)

    out["stopped_previous"] = previous["id"] if previous else None
    return out


def stop(db: DatabaseManager, project_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        e = (s.query(TimeEntry)
             .filter(TimeEntry.project_id == project_id,
                     TimeEntry.ended_at.is_(None))
             .order_by(TimeEntry.started_at.desc()).first())
        if not e:
            return None

        now = datetime.utcnow()
        elapsed = int((now - e.started_at).total_seconds() // 60)
        if elapsed > MAX_SESSION_MINUTES:
            # Forgotten overnight. The work happened; the duration is fiction.
            e.minutes = MAX_SESSION_MINUTES
            e.ended_at = e.started_at + timedelta(minutes=MAX_SESSION_MINUTES)
            e.note = (e.note or "") + " [capped: timer left running]"
        else:
            e.minutes = max(0, elapsed)
            e.ended_at = now
        s.commit()
        return _entry_dict(e)


def log(db: DatabaseManager, project_id: str, minutes: int,
        feature_id: Optional[str] = None, note: str = "",
        when: Optional[str] = None) -> Dict[str, Any]:
    """Record time after the fact."""
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise TimeError("Minutes must be a number.")
    if minutes <= 0:
        raise TimeError("Log a positive number of minutes.")
    if minutes > MAX_SESSION_MINUTES:
        raise TimeError(f"That is more than {effort.humanise(MAX_SESSION_MINUTES)} "
                        "in one entry — split it across days.")

    started = datetime.utcnow() - timedelta(minutes=minutes)
    if when:
        try:
            started = datetime.fromisoformat(when)
        except ValueError:
            raise TimeError("Dates must be ISO format.")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise TimeError("Project not found.")
        if feature_id and not s.get(FeatureBacklog, feature_id):
            raise TimeError("Feature not found.")
        entry = TimeEntry(
            id=str(uuid.uuid4()), project_id=project_id, feature_id=feature_id,
            started_at=started, ended_at=started + timedelta(minutes=minutes),
            minutes=minutes, source="manual", note=note[:500],
        )
        s.add(entry)
        s.commit()
        return _entry_dict(entry)


def delete(db: DatabaseManager, entry_id: str) -> bool:
    """Remove an entry. The only correction available — see the module docstring."""
    with db.get_session() as s:
        e = s.get(TimeEntry, entry_id)
        if not e:
            return False
        s.delete(e)
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
def spent_on(db: DatabaseManager, feature_id: str) -> int:
    """Minutes recorded against one item, including a running timer."""
    with db.get_session() as s:
        rows = s.query(TimeEntry).filter(TimeEntry.feature_id == feature_id).all()
        total = 0
        now = datetime.utcnow()
        for e in rows:
            if e.ended_at is None:
                total += int((now - e.started_at).total_seconds() // 60)
            else:
                total += e.minutes or 0
        return total


def spent_map(db: DatabaseManager, project_id: str) -> Dict[str, int]:
    """Minutes per feature, in one read.

    The scheduler needs this for every candidate at once; asking per item
    would be a query per row on the hot path.
    """
    with db.get_session() as s:
        rows = (s.query(TimeEntry)
                .filter(TimeEntry.project_id == project_id,
                        TimeEntry.feature_id.isnot(None)).all())
    out: Dict[str, int] = {}
    now = datetime.utcnow()
    for e in rows:
        minutes = (int((now - e.started_at).total_seconds() // 60)
                   if e.ended_at is None else (e.minutes or 0))
        out[e.feature_id] = out.get(e.feature_id, 0) + minutes
    return out


def list_entries(db: DatabaseManager, project_id: str,
                 feature_id: Optional[str] = None,
                 days: int = 30, limit: int = 200) -> List[Dict[str, Any]]:
    since = datetime.utcnow() - timedelta(days=days)
    with db.get_session() as s:
        q = s.query(TimeEntry).filter(TimeEntry.project_id == project_id,
                                      TimeEntry.started_at >= since)
        if feature_id:
            q = q.filter(TimeEntry.feature_id == feature_id)
        rows = q.order_by(TimeEntry.started_at.desc()).limit(limit).all()
        return [_entry_dict(e) for e in rows]


def day_summary(db: DatabaseManager, project_id: str,
                on: Optional[str] = None) -> Dict[str, Any]:
    """What a given day actually went on."""
    try:
        target = (datetime.fromisoformat(on).date() if on
                  else datetime.utcnow().date())
    except ValueError:
        raise TimeError("Dates must be ISO format (YYYY-MM-DD).")

    start_dt = datetime.combine(target, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    with db.get_session() as s:
        rows = (s.query(TimeEntry)
                .filter(TimeEntry.project_id == project_id,
                        TimeEntry.started_at >= start_dt,
                        TimeEntry.started_at < end_dt).all())
        titles = {f.id: f.title for f in s.query(FeatureBacklog)
                  .filter(FeatureBacklog.project_id == project_id).all()}

    by_feature: Dict[str, int] = {}
    untracked = 0
    now = datetime.utcnow()
    for e in rows:
        minutes = (int((now - e.started_at).total_seconds() // 60)
                   if e.ended_at is None else (e.minutes or 0))
        if e.feature_id:
            by_feature[e.feature_id] = by_feature.get(e.feature_id, 0) + minutes
        else:
            untracked += minutes

    total = sum(by_feature.values()) + untracked
    return {
        "date": target.isoformat(),
        "total_minutes": total,
        "total_human": effort.humanise(total),
        "untracked_minutes": untracked,
        "entries": len(rows),
        "by_feature": sorted(
            [{"feature_id": fid, "title": titles.get(fid, "(removed)"),
              "minutes": m, "human": effort.humanise(m)}
             for fid, m in by_feature.items()],
            key=lambda x: -x["minutes"]),
    }


def week_summary(db: DatabaseManager, project_id: str,
                 weeks: int = 4) -> Dict[str, Any]:
    """Daily totals, zero-filled, so a gap reads as a gap."""
    today = datetime.utcnow().date()
    start = today - timedelta(days=weeks * 7 - 1)

    with db.get_session() as s:
        rows = (s.query(TimeEntry)
                .filter(TimeEntry.project_id == project_id,
                        TimeEntry.started_at >= datetime.combine(
                            start, datetime.min.time())).all())

    per_day: Dict[str, int] = {}
    now = datetime.utcnow()
    for e in rows:
        minutes = (int((now - e.started_at).total_seconds() // 60)
                   if e.ended_at is None else (e.minutes or 0))
        d = e.started_at.date().isoformat()
        per_day[d] = per_day.get(d, 0) + minutes

    days = []
    for i in range(weeks * 7):
        d = (start + timedelta(days=i)).isoformat()
        days.append({"date": d, "minutes": per_day.get(d, 0)})

    tracked = [d["minutes"] for d in days if d["minutes"] > 0]
    total = sum(d["minutes"] for d in days)
    return {
        "days": days,
        "total_minutes": total,
        "total_human": effort.humanise(total),
        "days_tracked": len(tracked),
        "average_tracked_day": effort.humanise(
            sum(tracked) / len(tracked)) if tracked else "0m",
    }
