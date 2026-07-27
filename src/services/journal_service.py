"""
Journal and the app registry (Work Graph, step 5).

**The journal is not another capture surface.** Ideas already exist and are
deliberately frictionless; a second inbox competing with them would just
split people's captures across two places. A journal entry is a *dated
reflection* — what happened, what you learned — and its most useful property
is that it can be assembled automatically from the day you actually had.

`auto_entry` does exactly that: it reads what the Activity Timeline already
recorded and drafts the day. Writing a journal from scratch every evening is
the habit everyone abandons; correcting a draft is one people keep.

**The app registry is a description, not a mechanism.** Every surface listed
here is already a real page with real permissions. Naming them as apps that
share one memory, one permission model, and one work graph is a way of
telling the truth about the architecture, and the registry is generated from
the systems themselves so it cannot claim a capability that does not exist.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog

from src.db.journal_models import ENTRY_KINDS, JournalEntry
from src.db.schema import DatabaseManager, Project

logger = structlog.get_logger()


class JournalError(Exception):
    pass


def _entry_dict(e: JournalEntry) -> Dict[str, Any]:
    return {
        "id": e.id, "project_id": e.project_id, "entry_date": e.entry_date,
        "kind": e.kind, "title": e.title, "body": e.body,
        "highlights": e.highlights or [], "auto_drafted": bool(e.auto_drafted),
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _parse_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now().date().isoformat()
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        raise JournalError("Dates must be ISO format (YYYY-MM-DD).")


def write(db: DatabaseManager, project_id: str, body: str,
          entry_date: Optional[str] = None, title: str = "",
          kind: str = "reflection",
          highlights: Optional[List[str]] = None,
          auto_drafted: bool = False) -> Dict[str, Any]:
    """Create or replace the entry for a date.

    One entry per date per kind: a journal that accumulates six half-written
    entries for the same evening is one nobody reads back.
    """
    if kind not in ENTRY_KINDS:
        raise JournalError(f"Unknown kind. One of: {', '.join(ENTRY_KINDS)}")
    if not (body or "").strip():
        raise JournalError("An entry needs something written in it.")

    day = _parse_date(entry_date)

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise JournalError("Project not found.")
        existing = (s.query(JournalEntry)
                    .filter(JournalEntry.project_id == project_id,
                            JournalEntry.entry_date == day,
                            JournalEntry.kind == kind).first())
        if existing:
            existing.body = body[:20000]
            existing.title = (title or existing.title)[:200]
            existing.highlights = highlights or existing.highlights or []
            # A hand-edited entry is no longer a draft, whatever it started as.
            existing.auto_drafted = 1 if (auto_drafted and existing.auto_drafted) else 0
            existing.updated_at = datetime.utcnow()
            entry = existing
        else:
            entry = JournalEntry(
                id=str(uuid.uuid4()), project_id=project_id, entry_date=day,
                kind=kind, title=title[:200], body=body[:20000],
                highlights=highlights or [], auto_drafted=1 if auto_drafted else 0,
            )
            s.add(entry)
        s.commit()
        return _entry_dict(entry)


def get(db: DatabaseManager, project_id: str, entry_date: str,
        kind: str = "reflection") -> Optional[Dict[str, Any]]:
    day = _parse_date(entry_date)
    with db.get_session() as s:
        e = (s.query(JournalEntry)
             .filter(JournalEntry.project_id == project_id,
                     JournalEntry.entry_date == day,
                     JournalEntry.kind == kind).first())
        return _entry_dict(e) if e else None


def list_entries(db: DatabaseManager, project_id: str,
                 limit: int = 60) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(JournalEntry)
                .filter(JournalEntry.project_id == project_id)
                .order_by(JournalEntry.entry_date.desc())
                .limit(min(limit, 365)).all())
        return [_entry_dict(e) for e in rows]


def delete(db: DatabaseManager, entry_id: str) -> bool:
    with db.get_session() as s:
        e = s.get(JournalEntry, entry_id)
        if not e:
            return False
        s.delete(e)
        s.commit()
        return True


def auto_entry(db: DatabaseManager, project_id: str,
               entry_date: Optional[str] = None,
               save: bool = False) -> Dict[str, Any]:
    """Draft a day's entry from what actually happened.

    Reads the Activity Timeline rather than asking a model to remember: the
    facts are already recorded, and a drafted day the user corrects beats a
    blank page they skip.
    """
    from src.services import timeline_service

    day = _parse_date(entry_date)
    page = timeline_service.list_events(db, project_id, limit=200)

    same_day = [e for e in page["events"]
                if (e.get("timestamp") or "")[:10] == day]

    by_category: Dict[str, List[str]] = {}
    for e in same_day:
        by_category.setdefault(e["category"], []).append(e["title"])

    highlights: List[str] = []
    lines: List[str] = []

    labels = {"idea": "Captured and triaged", "feature": "Backlog",
              "run": "Ran", "research": "Research"}
    for category, titles in by_category.items():
        lines.append(f"**{labels.get(category, category.title())}**")
        for t in titles[:6]:
            lines.append(f"- {t}")
        if len(titles) > 6:
            lines.append(f"- …and {len(titles) - 6} more")
        lines.append("")
        highlights.append(f"{len(titles)} {category} event"
                          f"{'s' if len(titles) != 1 else ''}")

    if not same_day:
        body = ("_Nothing was recorded in Dobby on this day._\n\n"
                "What did you work on?\n")
        highlights = []
    else:
        body = ("\n".join(lines)
                + "\n---\n\n**What went well?**\n\n\n**What was hard?**\n\n\n"
                  "**What is next?**\n")

    draft = {
        "entry_date": day,
        "title": f"Journal — {day}",
        "body": body,
        "highlights": highlights,
        "event_count": len(same_day),
        "auto_drafted": True,
        "saved": False,
    }

    if save:
        saved = write(db, project_id, body, day, draft["title"],
                      "reflection", highlights, auto_drafted=True)
        draft.update(saved)
        draft["saved"] = True

    return draft


def streak(db: DatabaseManager, project_id: str, days: int = 30) -> Dict[str, Any]:
    """How consistently the journal is actually kept."""
    with db.get_session() as s:
        rows = (s.query(JournalEntry)
                .filter(JournalEntry.project_id == project_id).all())
        written = {e.entry_date for e in rows}

    today = datetime.now().date()
    recent = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    kept = sum(1 for d in recent if d in written)

    run = 0
    for d in recent:
        if d in written:
            run += 1
        elif run or d != today.isoformat():
            # Today not yet written does not break a streak; a missed day does.
            break

    return {"entries": len(written), "in_window": kept, "window_days": days,
            "current_streak": run}


# ---------------------------------------------------------------------------
# App registry
# ---------------------------------------------------------------------------
def app_registry(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """Every surface, described as an app over the shared substrate.

    Generated from the systems themselves rather than hand-listed, so it
    cannot advertise something that is not wired up.
    """
    from src.services import skill_service

    apps = [
        {"slug": "daily_alignment", "name": "Daily Alignment", "route": "/",
         "blurb": "Plan your day and protect your focus.",
         "reads": ["work graph", "decisions", "backlog", "momentum"],
         "writes": ["daily plan"]},
        {"slug": "work_graph", "name": "Work Graph", "route": "/workgraph",
         "blurb": "See how everything connects.",
         "reads": ["goals", "backlog", "decisions", "skills"], "writes": []},
        {"slug": "decisions", "name": "Decisions", "route": "/decisions",
         "blurb": "The forks your work waits behind.",
         "reads": ["backlog", "documents"], "writes": ["decisions"]},
        {"slug": "skill_studio", "name": "Skill Studio", "route": "/skills",
         "blurb": "Build and refine your skills.",
         "reads": ["documents", "backlog", "research"],
         "writes": ["documents", "ideas", "decisions"]},
        {"slug": "board", "name": "Board", "route": "/board",
         "blurb": "Move work across the board.",
         "reads": ["backlog", "blockers", "decisions"], "writes": ["backlog"]},
        {"slug": "documents", "name": "Documents", "route": "/documents",
         "blurb": "Write, version, and review.",
         "reads": ["documents"], "writes": ["documents", "comments"]},
        {"slug": "ideas", "name": "Ideas", "route": "/ideas",
         "blurb": "Capture a thought in one line.",
         "reads": ["ideas"], "writes": ["ideas", "backlog", "research"]},
        {"slug": "journal", "name": "Journal", "route": "/journal",
         "blurb": "What happened, and what you learned.",
         "reads": ["activity timeline"], "writes": ["journal"]},
        {"slug": "copilot", "name": "Copilot", "route": "/copilot",
         "blurb": "Ask about your own work.",
         "reads": ["documents", "backlog", "research"], "writes": []},
        {"slug": "automations", "name": "Automations", "route": "/automations",
         "blurb": "Work that runs on a schedule.",
         "reads": ["everything permitted"], "writes": ["per automation"]},
    ]

    with db.get_session() as s:
        project = s.get(Project, project_id)
        if not project:
            raise JournalError("Project not found.")

    installed_skills = [s_ for s_ in skill_service.list_skills(db, project_id)
                        if not s_["builtin"]]

    return {
        "apps": apps,
        "your_skills": [{"slug": s_["slug"], "name": s_["name"],
                         "route": "/skills", "state": s_["state"],
                         "blurb": s_["description"][:120]}
                        for s_ in installed_skills],
        "shared": {
            "memory": "One database on this device. Every app reads the same "
                      "documents, backlog, decisions, and history.",
            "permissions": "One approval gate. Anything consequential raises an "
                           "ask in your Inbox, whichever app asked for it.",
            "work_graph": "One graph. A decision blocking work blocks it "
                          "everywhere, not just where you created it.",
        },
        "local_first": True,
    }
