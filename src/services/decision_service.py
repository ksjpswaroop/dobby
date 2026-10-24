"""
Decisions — the forks work waits behind (Work Graph, step 1).

The load-bearing function here is `blocked_entity_ids`. An open decision that
blocks a feature removes that feature from the ready set exactly like an
unfinished `Blocker` does, which is what turns "the current decision is the
main blocker for this project" from a slogan into a computed fact.

Deciding is append-only: the chosen option, rationale, and timestamp are
written once. Changing your mind creates a *superseding* decision rather than
editing the original, so the record of what you believed in July survives you
disagreeing with it in September.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import structlog

from src.db.decision_models import (
    DECISION_STATES, LINK_TYPES, Decision, DecisionLink, DecisionOption,
)
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project

logger = structlog.get_logger()

# How far ahead a due date counts as "coming up" rather than merely existing.
DUE_SOON_DAYS = 3


class DecisionError(Exception):
    pass


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise DecisionError("Dates must be ISO format (YYYY-MM-DD).")


def _option_dict(o: DecisionOption, chosen_id: Optional[str]) -> Dict[str, Any]:
    return {
        "id": o.id, "label": o.label, "note": o.note,
        "sort_order": o.sort_order or 0,
        "chosen": chosen_id == o.id,
    }


def _decision_dict(s, d: Decision) -> Dict[str, Any]:
    options = (s.query(DecisionOption)
               .filter(DecisionOption.decision_id == d.id)
               .order_by(DecisionOption.sort_order).all())
    links = s.query(DecisionLink).filter(DecisionLink.decision_id == d.id).all()

    now = datetime.utcnow()
    due = d.due_on
    overdue = bool(due and d.status == "open" and due < now)
    due_soon = bool(due and d.status == "open" and not overdue
                    and due <= now + timedelta(days=DUE_SOON_DAYS))

    return {
        "id": d.id,
        "project_id": d.project_id,
        "title": d.title,
        "question": d.question,
        "status": d.status,
        "due_on": due.date().isoformat() if due else None,
        "days_until_due": (due.date() - now.date()).days if due else None,
        "overdue": overdue,
        "due_soon": due_soon,
        "chosen_option_id": d.chosen_option_id,
        "rationale": d.rationale,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "superseded_by": d.superseded_by,
        "options": [_option_dict(o, d.chosen_option_id) for o in options],
        "links": [{"id": l.id, "entity_type": l.entity_type,
                   "entity_id": l.entity_id, "blocking": bool(l.blocking)}
                  for l in links],
        "blocking_count": sum(1 for l in links if l.blocking) if d.status == "open" else 0,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create(db: DatabaseManager, project_id: str, title: str, question: str = "",
           due_on: Optional[str] = None,
           options: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise DecisionError("A decision needs a title.")
    due = _parse_date(due_on)

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise DecisionError("Project not found.")
        decision = Decision(
            id=str(uuid.uuid4()), project_id=project_id, title=title[:300],
            question=(question or "")[:4000], status="open", due_on=due,
        )
        s.add(decision)
        s.flush()

        for i, opt in enumerate(options or []):
            label = str(opt.get("label", "")).strip()
            if not label:
                continue
            s.add(DecisionOption(
                id=str(uuid.uuid4()), decision_id=decision.id, label=label[:200],
                note=str(opt.get("note", ""))[:2000], sort_order=i,
            ))
        s.commit()
        return _decision_dict(s, decision)


def get(db: DatabaseManager, decision_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        d = s.get(Decision, decision_id)
        return _decision_dict(s, d) if d else None


def list_decisions(db: DatabaseManager, project_id: str,
                   status: Optional[str] = None) -> List[Dict[str, Any]]:
    if status and status not in DECISION_STATES:
        raise DecisionError(f"Unknown status. One of: {', '.join(DECISION_STATES)}")
    with db.get_session() as s:
        q = s.query(Decision).filter(Decision.project_id == project_id)
        if status:
            q = q.filter(Decision.status == status)
        rows = q.all()
        out = [_decision_dict(s, d) for d in rows]

    # Most urgent first: overdue, then due soon, then by how much work is
    # waiting, then newest. An undated decision blocking three things should
    # outrank a dated one blocking nothing.
    out.sort(key=lambda d: (
        not d["overdue"],
        not d["due_soon"],
        -d["blocking_count"],
        d["days_until_due"] if d["days_until_due"] is not None else 9999,
    ))
    return out


def add_option(db: DatabaseManager, decision_id: str, label: str,
               note: str = "") -> Dict[str, Any]:
    label = (label or "").strip()
    if not label:
        raise DecisionError("An option needs a label.")
    with db.get_session() as s:
        d = s.get(Decision, decision_id)
        if not d:
            raise DecisionError("Decision not found.")
        if d.status != "open":
            raise DecisionError("This decision has already been made.")
        count = (s.query(DecisionOption)
                 .filter(DecisionOption.decision_id == decision_id).count())
        s.add(DecisionOption(id=str(uuid.uuid4()), decision_id=decision_id,
                             label=label[:200], note=note[:2000], sort_order=count))
        s.commit()
        return _decision_dict(s, d)


def remove_option(db: DatabaseManager, option_id: str) -> bool:
    with db.get_session() as s:
        o = s.get(DecisionOption, option_id)
        if not o:
            return False
        d = s.get(Decision, o.decision_id)
        if d and d.status != "open":
            raise DecisionError("Cannot change the options of a decision already made.")
        s.delete(o)
        s.commit()
        return True


def update(db: DatabaseManager, decision_id: str, title: Optional[str] = None,
           question: Optional[str] = None,
           due_on: Optional[str] = None) -> Dict[str, Any]:
    with db.get_session() as s:
        d = s.get(Decision, decision_id)
        if not d:
            raise DecisionError("Decision not found.")
        if title is not None:
            if not title.strip():
                raise DecisionError("A decision needs a title.")
            d.title = title.strip()[:300]
        if question is not None:
            d.question = question[:4000]
        if due_on is not None:
            d.due_on = _parse_date(due_on) if due_on else None
        d.updated_at = datetime.utcnow()
        s.commit()
        return _decision_dict(s, d)


def delete(db: DatabaseManager, decision_id: str) -> bool:
    with db.get_session() as s:
        d = s.get(Decision, decision_id)
        if not d:
            return False
        for row in s.query(DecisionOption).filter(
                DecisionOption.decision_id == decision_id).all():
            s.delete(row)
        for row in s.query(DecisionLink).filter(
                DecisionLink.decision_id == decision_id).all():
            s.delete(row)
        # Flush the children before the parent: SQLAlchemy batches deletes and
        # does not guarantee the order, which trips the foreign key.
        s.flush()
        s.delete(d)
        s.commit()
        return True


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------
def decide(db: DatabaseManager, decision_id: str, option_id: str,
           rationale: str = "") -> Dict[str, Any]:
    with db.get_session() as s:
        d = s.get(Decision, decision_id)
        if not d:
            raise DecisionError("Decision not found.")
        if d.status != "open":
            raise DecisionError("This decision has already been made. "
                                "Supersede it instead of editing history.")
        option = s.get(DecisionOption, option_id)
        if not option or option.decision_id != decision_id:
            raise DecisionError("That option does not belong to this decision.")

        d.chosen_option_id = option_id
        d.rationale = (rationale or "")[:4000]
        d.status = "decided"
        d.decided_at = datetime.utcnow()
        s.commit()
        return _decision_dict(s, d)


def supersede(db: DatabaseManager, decision_id: str, title: str,
              question: str = "", due_on: Optional[str] = None,
              options: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Replace a decision with a new one, preserving the original as history."""
    with db.get_session() as s:
        old = s.get(Decision, decision_id)
        if not old:
            raise DecisionError("Decision not found.")
        if old.status == "superseded":
            raise DecisionError("That decision has already been superseded.")
        project_id = old.project_id
        old_links = [(l.entity_type, l.entity_id, l.blocking)
                     for l in s.query(DecisionLink)
                     .filter(DecisionLink.decision_id == decision_id).all()]

    new = create(db, project_id, title, question, due_on, options)

    # The work that was waiting on the old decision is waiting on the new one.
    for entity_type, entity_id, blocking in old_links:
        try:
            link(db, new["id"], entity_type, entity_id, bool(blocking))
        except DecisionError:
            continue

    with db.get_session() as s:
        old = s.get(Decision, decision_id)
        old.status = "superseded"
        old.superseded_by = new["id"]
        old.updated_at = datetime.utcnow()
        s.commit()

    return get(db, new["id"])


# ---------------------------------------------------------------------------
# Links & blocking
# ---------------------------------------------------------------------------
def link(db: DatabaseManager, decision_id: str, entity_type: str,
         entity_id: str, blocking: bool = True) -> Dict[str, Any]:
    if entity_type not in LINK_TYPES:
        raise DecisionError(f"Unknown link type. One of: {', '.join(LINK_TYPES)}")

    with db.get_session() as s:
        d = s.get(Decision, decision_id)
        if not d:
            raise DecisionError("Decision not found.")

        if entity_type == "feature" and not s.get(FeatureBacklog, entity_id):
            raise DecisionError("Feature not found.")
        if entity_type == "document" and not s.get(Node, entity_id):
            raise DecisionError("Document not found.")

        existing = (s.query(DecisionLink)
                    .filter(DecisionLink.decision_id == decision_id,
                            DecisionLink.entity_type == entity_type,
                            DecisionLink.entity_id == entity_id).first())
        if existing:
            existing.blocking = 1 if blocking else 0
        else:
            s.add(DecisionLink(
                id=str(uuid.uuid4()), decision_id=decision_id,
                project_id=d.project_id, entity_type=entity_type,
                entity_id=entity_id, blocking=1 if blocking else 0,
            ))
        s.commit()
        return _decision_dict(s, d)


def unlink(db: DatabaseManager, link_id: str) -> bool:
    with db.get_session() as s:
        l = s.get(DecisionLink, link_id)
        if not l:
            return False
        s.delete(l)
        s.commit()
        return True


def blocked_entity_ids(db: DatabaseManager, project_id: str,
                       entity_type: str = "feature") -> Set[str]:
    """Entities held up by an *open* decision.

    A decided or superseded decision blocks nothing — that is the whole point
    of deciding — so only `open` counts here.
    """
    with db.get_session() as s:
        open_ids = {d.id for d in s.query(Decision)
                    .filter(Decision.project_id == project_id,
                            Decision.status == "open").all()}
        if not open_ids:
            return set()
        return {l.entity_id for l in s.query(DecisionLink)
                .filter(DecisionLink.project_id == project_id,
                        DecisionLink.entity_type == entity_type,
                        DecisionLink.blocking == 1).all()
                if l.decision_id in open_ids}


def blockers_for(db: DatabaseManager, project_id: str, entity_type: str,
                 entity_id: str) -> List[Dict[str, Any]]:
    """The open decisions holding up one specific thing."""
    with db.get_session() as s:
        links = (s.query(DecisionLink)
                 .filter(DecisionLink.project_id == project_id,
                         DecisionLink.entity_type == entity_type,
                         DecisionLink.entity_id == entity_id,
                         DecisionLink.blocking == 1).all())
        out = []
        for l in links:
            d = s.get(Decision, l.decision_id)
            if d and d.status == "open":
                out.append(_decision_dict(s, d))
        return out


def pending_summary(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """What the dashboard and next-best-action need in one read."""
    decisions = list_decisions(db, project_id, status="open")
    return {
        "open": len(decisions),
        "overdue": sum(1 for d in decisions if d["overdue"]),
        "due_soon": sum(1 for d in decisions if d["due_soon"]),
        "blocking_work": sum(1 for d in decisions if d["blocking_count"] > 0),
        # The one to surface: the sort already puts the most urgent first.
        "most_urgent": decisions[0] if decisions else None,
    }
