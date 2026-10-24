"""
Pins & Favorites (100-Day Roadmap, Day 8).

`list_pins` is where dangling-pin cleanup happens: rather than a periodic
sweep, a pin whose target no longer resolves is deleted the next time
anyone actually looks at the pinned list. Nothing else needs to know a
target was deleted for the pin referencing it to disappear.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.db.idea_models import Idea
from src.db.pin_models import ENTITY_TYPES, Pin
from src.db.schema import DatabaseManager, FeatureBacklog, Node


class PinError(Exception):
    pass


def _resolve(s, entity_type: str, entity_id: str) -> Optional[Dict[str, str]]:
    if entity_type == "idea":
        row = s.get(Idea, entity_id)
        return {"title": row.text[:120], "route": "/ideas"} if row else None
    if entity_type == "feature":
        row = s.get(FeatureBacklog, entity_id)
        return {"title": row.title, "route": "/backlog"} if row else None
    if entity_type == "document":
        row = s.get(Node, entity_id)
        return {"title": row.title, "route": "/documents"} if row else None
    return None


def _pin_dict(pin: Pin, resolved: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": pin.id,
        "entity_type": pin.entity_type,
        "entity_id": pin.entity_id,
        "order_index": pin.order_index,
        "title": resolved["title"],
        "route": resolved["route"],
        "created_at": pin.created_at.isoformat() if pin.created_at else None,
    }


def pin(db: DatabaseManager, project_id: str, entity_type: str, entity_id: str) -> Dict[str, Any]:
    if entity_type not in ENTITY_TYPES:
        raise PinError(f"Unknown entity type. One of: {', '.join(ENTITY_TYPES)}")

    with db.get_session() as s:
        resolved = _resolve(s, entity_type, entity_id)
        if not resolved:
            raise PinError("That item no longer exists.")

        existing = (s.query(Pin)
                    .filter(Pin.project_id == project_id, Pin.entity_type == entity_type,
                            Pin.entity_id == entity_id)
                    .first())
        if existing:
            return _pin_dict(existing, resolved)

        max_order = (s.query(Pin).filter(Pin.project_id == project_id)
                     .count())
        row = Pin(id=str(uuid.uuid4()), project_id=project_id, entity_type=entity_type,
                  entity_id=entity_id, order_index=max_order, created_at=datetime.utcnow())
        s.add(row)
        s.commit()
        return _pin_dict(row, resolved)


def unpin(db: DatabaseManager, project_id: str, entity_type: str, entity_id: str) -> bool:
    with db.get_session() as s:
        row = (s.query(Pin)
               .filter(Pin.project_id == project_id, Pin.entity_type == entity_type,
                       Pin.entity_id == entity_id)
               .first())
        if not row:
            return False
        s.delete(row)
        s.flush()
        # Re-flow remaining order indices so unpinning never leaves gaps.
        remaining = (s.query(Pin).filter(Pin.project_id == project_id)
                     .order_by(Pin.order_index).all())
        for i, p in enumerate(remaining):
            p.order_index = i
        s.commit()
        return True


def list_pins(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(Pin).filter(Pin.project_id == project_id)
                .order_by(Pin.order_index).all())
        out: List[Dict[str, Any]] = []
        dangling: List[Pin] = []
        for row in rows:
            resolved = _resolve(s, row.entity_type, row.entity_id)
            if resolved:
                out.append(_pin_dict(row, resolved))
            else:
                dangling.append(row)

        if dangling:
            for row in dangling:
                s.delete(row)
            s.flush()
            remaining = (s.query(Pin).filter(Pin.project_id == project_id)
                        .order_by(Pin.order_index).all())
            for i, p in enumerate(remaining):
                p.order_index = i
            s.commit()

        return out


def reorder(db: DatabaseManager, project_id: str, pin_ids: List[str]) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = {p.id: p for p in s.query(Pin).filter(Pin.project_id == project_id).all()}
        if set(pin_ids) != set(rows.keys()):
            raise PinError("Reorder must include exactly the current set of pins.")
        for i, pid in enumerate(pin_ids):
            rows[pid].order_index = i
        s.commit()
    return list_pins(db, project_id)


def is_pinned(db: DatabaseManager, project_id: str, entity_type: str, entity_id: str) -> bool:
    with db.get_session() as s:
        return (s.query(Pin)
                .filter(Pin.project_id == project_id, Pin.entity_type == entity_type,
                        Pin.entity_id == entity_id)
                .first() is not None)
