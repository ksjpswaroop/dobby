"""
Habit, delight & retention (100-Day Roadmap, Phase 8: Days 71-80).

Everything here is a *nudge*, and nudges are the fastest way to make someone
uninstall an app. Two rules follow from that:

**One notification manager gates every nudge.** Reminders, recaps,
achievements, resurfacing — all of them go through `should_notify()`, which
enforces quiet hours, per-category mute, and a once-per-day-per-category cap.
Without a single gate, six features each individually reasonable add up to an
app that pesters you.

**Achievements are derived, never incremented.** A badge is a query over real
state, so it cannot drift out of sync with the thing it claims to celebrate,
and a bug in a counter can never award a badge you did not earn.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional

from src.db.idea_models import Idea
from src.db.planning_models import FeatureStatusChange
from src.db.run_models import Run
from src.db.schema import DatabaseManager, FeatureBacklog, Node
from src.services import momentum_service

NOTIFICATION_CATEGORIES = (
    "daily_reminder", "weekly_recap", "achievement", "resurfacing", "focus",
)

# Badges are pure predicates over real state — see the module docstring.
BADGES = [
    {"slug": "first_capture", "name": "First thought", "hint": "Capture your first idea."},
    {"slug": "first_document", "name": "First draft", "hint": "Generate your first document."},
    {"slug": "full_set", "name": "Full set", "hint": "Generate all seven artifacts for one feature."},
    {"slug": "triager", "name": "Triager", "hint": "Triage 10 captured ideas."},
    {"slug": "closer", "name": "Closer", "hint": "Complete 10 backlog items."},
    {"slug": "streak_7", "name": "Week one", "hint": "Build 7 days in a row."},
    {"slug": "streak_30", "name": "Month strong", "hint": "Build 30 days in a row."},
    {"slug": "librarian", "name": "Librarian", "hint": "Write 25 documents."},
    {"slug": "researcher", "name": "Researcher", "hint": "Run 5 research briefs."},
]

DEFAULT_FOCUS_MINUTES = 25
DEFAULT_BREAK_MINUTES = 5


class HabitError(Exception):
    pass


# ---------------------------------------------------------------------------
# Notification gate (D80)
# ---------------------------------------------------------------------------
def _notification_settings() -> Dict[str, Any]:
    from src.settings import get_settings

    s = get_settings()
    return {
        "enabled": getattr(s, "notifications_enabled", True),
        "quiet_start": getattr(s, "quiet_hours_start", 22),
        "quiet_end": getattr(s, "quiet_hours_end", 8),
        "muted": list(getattr(s, "muted_notifications", None) or []),
        "last_sent": dict(getattr(s, "notification_last_sent", None) or {}),
    }


def in_quiet_hours(now_hour: int, start: int, end: int) -> bool:
    """Quiet hours usually wrap midnight, so a naive start<=h<end is wrong."""
    if start == end:
        return False
    if start < end:
        return start <= now_hour < end
    return now_hour >= start or now_hour < end


def should_notify(category: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The single gate every nudge passes through."""
    if category not in NOTIFICATION_CATEGORIES:
        raise HabitError(f"Unknown category. One of: {', '.join(NOTIFICATION_CATEGORIES)}")

    now = now or datetime.now()
    cfg = _notification_settings()

    if not cfg["enabled"]:
        return {"allowed": False, "reason": "Notifications are off."}
    if category in cfg["muted"]:
        return {"allowed": False, "reason": f"{category} is muted."}
    if in_quiet_hours(now.hour, cfg["quiet_start"], cfg["quiet_end"]):
        return {"allowed": False,
                "reason": f"Quiet hours ({cfg['quiet_start']}:00–{cfg['quiet_end']}:00)."}

    last = cfg["last_sent"].get(category)
    if last:
        try:
            if datetime.fromisoformat(last).date() == now.date():
                return {"allowed": False, "reason": "Already sent today."}
        except ValueError:
            pass

    return {"allowed": True, "reason": ""}


def mark_notified(category: str, now: Optional[datetime] = None) -> Dict[str, str]:
    from src.settings import get_settings, get_settings_store

    now = now or datetime.now()
    sent = dict(getattr(get_settings(), "notification_last_sent", None) or {})
    sent[category] = now.isoformat()
    get_settings_store().update(notification_last_sent=sent)
    return sent


def set_muted(categories: List[str]) -> List[str]:
    unknown = [c for c in categories if c not in NOTIFICATION_CATEGORIES]
    if unknown:
        raise HabitError(f"Unknown categories: {', '.join(unknown)}")
    from src.settings import get_settings_store

    get_settings_store().update(muted_notifications=list(categories))
    return list(categories)


# ---------------------------------------------------------------------------
# Daily reminder (D71)
# ---------------------------------------------------------------------------
def daily_reminder(db: DatabaseManager, project_id: str,
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    """What today's nudge would say, and whether it is allowed to be shown."""
    gate = should_notify("daily_reminder", now)
    from src.services import home_service

    home = home_service.build_home(db, project_id)
    waiting = len(home.get("needs_triage", [])) + len(home.get("needs_decision", []))
    momentum = momentum_service.get_momentum(db, project_id)

    if momentum["active_today"]:
        message = "You've already built today. Anything else is a bonus."
    elif waiting:
        message = f"{waiting} thing{'s' if waiting != 1 else ''} waiting on you in Dobby."
    elif momentum["streak"]:
        message = f"Your {momentum['streak']}-day streak is still alive. Ten minutes keeps it going."
    else:
        message = "Capture one idea today — that's all it takes to start."

    return {"allowed": gate["allowed"], "reason": gate["reason"],
            "message": message, "waiting": waiting, "streak": momentum["streak"]}


# ---------------------------------------------------------------------------
# Weekly recap (D72)
# ---------------------------------------------------------------------------
def weekly_recap(db: DatabaseManager, project_id: str,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.utcnow()
    since = now - timedelta(days=7)

    with db.get_session() as s:
        docs_written = (s.query(Node)
                        .filter(Node.project_id == project_id,
                                Node.updated_at >= since).count())
        ideas_captured = (s.query(Idea)
                          .filter(Idea.project_id == project_id,
                                  Idea.created_at >= since).count())
        ideas_triaged = (s.query(Idea)
                         .filter(Idea.project_id == project_id,
                                 Idea.status != "inbox",
                                 Idea.updated_at >= since).count())
        completed = (s.query(FeatureStatusChange)
                     .filter(FeatureStatusChange.project_id == project_id,
                             FeatureStatusChange.to_column == "done",
                             FeatureStatusChange.created_at >= since).count())
        runs = (s.query(Run)
                .filter(Run.project_id == project_id,
                        Run.started_at >= since).count())

    momentum = momentum_service.get_momentum(db, project_id)
    active_days = sum(1 for d in momentum["sparkline"][-7:] if d["count"] > 0)

    highlights = []
    if completed:
        highlights.append(f"closed {completed} backlog item{'s' if completed != 1 else ''}")
    if docs_written:
        highlights.append(f"worked on {docs_written} document{'s' if docs_written != 1 else ''}")
    if ideas_captured:
        highlights.append(f"captured {ideas_captured} idea{'s' if ideas_captured != 1 else ''}")

    if highlights:
        summary = "This week you " + ", ".join(highlights) + "."
    else:
        summary = "Quiet week in Dobby. A single capture is enough to restart."

    return {
        "period_days": 7,
        "documents_touched": docs_written,
        "ideas_captured": ideas_captured,
        "ideas_triaged": ideas_triaged,
        "items_completed": completed,
        "runs": runs,
        "active_days": active_days,
        "streak": momentum["streak"],
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Achievements (D73)
# ---------------------------------------------------------------------------
def achievements(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """Every badge, earned or not, computed from real state."""
    with db.get_session() as s:
        idea_count = s.query(Idea).filter(Idea.project_id == project_id).count()
        triaged = (s.query(Idea)
                   .filter(Idea.project_id == project_id,
                           Idea.status.in_(("backlog", "research", "archived"))).count())
        node_count = s.query(Node).filter(Node.project_id == project_id).count()
        completed = (s.query(FeatureBacklog)
                     .filter(FeatureBacklog.project_id == project_id,
                             FeatureBacklog.status == "completed").count())

        # A "full set" means one parent with all seven artifact types beneath it.
        nodes = s.query(Node).filter(Node.project_id == project_id).all()
        by_parent: Dict[Optional[str], set] = {}
        for n in nodes:
            by_parent.setdefault(n.parent_id, set()).add(n.node_type)
        full_set = any(len(types) >= 7 for types in by_parent.values())

        from src.db.research_models import ResearchBrief

        briefs = (s.query(ResearchBrief)
                  .filter(ResearchBrief.project_id == project_id).count())

    streak = momentum_service.get_momentum(db, project_id)["streak"]

    earned = {
        "first_capture": idea_count >= 1,
        "first_document": node_count >= 1,
        "full_set": full_set,
        "triager": triaged >= 10,
        "closer": completed >= 10,
        "streak_7": streak >= 7,
        "streak_30": streak >= 30,
        "librarian": node_count >= 25,
        "researcher": briefs >= 5,
    }

    progress = {
        "triager": min(1.0, triaged / 10),
        "closer": min(1.0, completed / 10),
        "streak_7": min(1.0, streak / 7),
        "streak_30": min(1.0, streak / 30),
        "librarian": min(1.0, node_count / 25),
        "researcher": min(1.0, briefs / 5),
    }

    badges = [{**b, "earned": earned.get(b["slug"], False),
               "progress": round(progress.get(b["slug"], 1.0 if earned.get(b["slug"]) else 0.0), 2)}
              for b in BADGES]

    return {"badges": badges,
            "earned_count": sum(1 for b in badges if b["earned"]),
            "total": len(badges)}


# ---------------------------------------------------------------------------
# On this day (D74)
# ---------------------------------------------------------------------------
def on_this_day(db: DatabaseManager, project_id: str,
                now: Optional[datetime] = None) -> Dict[str, Any]:
    """Things touched on this calendar day in previous weeks or months."""
    now = now or datetime.utcnow()
    today = now.date()

    with db.get_session() as s:
        nodes = s.query(Node).filter(Node.project_id == project_id).all()
        ideas = s.query(Idea).filter(Idea.project_id == project_id).all()

    memories = []

    def consider(created, kind: str, title: str, route: str):
        if not created:
            return
        d = created.date()
        age = (today - d).days
        if age < 7:
            return  # not yet a memory
        # Same weekday-anniversary (multiples of 7) or same day-of-month.
        if age % 7 == 0 or (d.day == today.day and d.month != today.month):
            memories.append({
                "kind": kind, "title": title, "route": route,
                "date": d.isoformat(), "days_ago": age,
            })

    for n in nodes:
        consider(n.created_at, "document", n.title or "Untitled",
                 f"/documents/{n.id}")
    for i in ideas:
        consider(i.created_at, "idea", (i.text or "")[:80], "/ideas")

    memories.sort(key=lambda m: m["days_ago"])
    return {"memories": memories[:5], "count": len(memories)}


# ---------------------------------------------------------------------------
# Focus mode (D75)
# ---------------------------------------------------------------------------
def focus_config() -> Dict[str, Any]:
    from src.settings import get_settings

    s = get_settings()
    return {
        "focus_minutes": getattr(s, "focus_minutes", DEFAULT_FOCUS_MINUTES),
        "break_minutes": getattr(s, "break_minutes", DEFAULT_BREAK_MINUTES),
    }


def set_focus_config(focus_minutes: int, break_minutes: int) -> Dict[str, Any]:
    if not (1 <= focus_minutes <= 180):
        raise HabitError("A focus interval must be between 1 and 180 minutes.")
    if not (1 <= break_minutes <= 60):
        raise HabitError("A break must be between 1 and 60 minutes.")
    from src.settings import get_settings_store

    get_settings_store().update(focus_minutes=focus_minutes, break_minutes=break_minutes)
    return focus_config()


# ---------------------------------------------------------------------------
# Share card (D79)
# ---------------------------------------------------------------------------
def share_card(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """An SVG celebrating the current streak, generated locally.

    SVG rather than a rendered PNG because it needs no image library, scales
    anywhere, and the user can see exactly what it says before sharing it —
    which matters for something explicitly meant to leave the machine.
    """
    momentum = momentum_service.get_momentum(db, project_id)
    recap = weekly_recap(db, project_id)
    streak = momentum["streak"]

    headline = (f"{streak}-day streak" if streak
                else f"{recap['items_completed']} shipped this week")
    sub = (f"{recap['documents_touched']} documents · "
           f"{recap['ideas_captured']} ideas · {recap['active_days']}/7 active days")

    bars = ""
    peak = max(1, *[d["count"] for d in momentum["sparkline"]]) if momentum["sparkline"] else 1
    for i, d in enumerate(momentum["sparkline"]):
        h = max(3, int((d["count"] / peak) * 46))
        bars += (f'<rect x="{40 + i * 22}" y="{210 - h}" width="12" height="{h}" '
                 f'rx="3" fill="{"#7c3aed" if d["count"] else "#e5e7eb"}"/>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="260" viewBox="0 0 480 260">
  <rect width="480" height="260" rx="24" fill="#faf9fc"/>
  <rect x="1" y="1" width="478" height="258" rx="23" fill="none" stroke="#e5e7eb"/>
  <text x="40" y="70" font-family="Helvetica, Arial, sans-serif" font-size="34"
        font-weight="600" fill="#1a1523">{headline}</text>
  <text x="40" y="102" font-family="Helvetica, Arial, sans-serif" font-size="14"
        fill="#6b7280">{sub}</text>
  {bars}
  <text x="40" y="240" font-family="Helvetica, Arial, sans-serif" font-size="12"
        fill="#9ca3af">Built locally with Dobby</text>
</svg>"""

    return {"svg": svg, "headline": headline, "subtitle": sub, "streak": streak}


# ---------------------------------------------------------------------------
# Menu-bar summary (D78)
# ---------------------------------------------------------------------------
def tray_summary(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """The small always-available glance a menu-bar widget renders."""
    from src.services import home_service

    momentum = momentum_service.get_momentum(db, project_id)
    home = home_service.build_home(db, project_id)

    with db.get_session() as s:
        running = (s.query(Run)
                   .filter(Run.project_id == project_id, Run.status == "running")
                   .count())

    return {
        "streak": momentum["streak"],
        "active_today": momentum["active_today"],
        "needs_triage": len(home.get("needs_triage", [])),
        "needs_decision": len(home.get("needs_decision", [])),
        "running": running,
        "clear": home.get("clear", False),
    }
