"""
Mind-map service — CRUD, tree assembly, and hierarchy validation.

The backend is the single source of truth for structural rules (cycles, orphans,
root uniqueness). The canvas may update optimistically, but an illegal move is
rejected here and the UI reverts — which avoids the drag-vs-autosave race the
plan flagged as a launch-blocking risk.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.mindmap_models import MindMap, MindMapEdge, MindMapNode, MindMapSnapshot
from src.db.schema import DatabaseManager

logger = structlog.get_logger()

NODE_TYPES = [
    "Idea", "Problem", "Opportunity", "Feature", "Risk",
    "Assumption", "Research Question", "Action Item", "Decision",
]


class MindMapError(Exception):
    """Raised for invalid structural operations (cycles, bad references)."""


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def node_dict(n: MindMapNode) -> Dict[str, Any]:
    return {
        "id": n.id,
        "mind_map_id": n.mind_map_id,
        "parent_id": n.parent_id,
        "title": n.title,
        "description": n.description or "",
        "node_type": n.node_type,
        "color": n.color,
        "sort_order": n.sort_order or 0,
        "metadata": n.extra_metadata or {},
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def map_dict(m: MindMap) -> Dict[str, Any]:
    return {
        "id": m.id,
        "project_id": m.project_id,
        "session_id": m.session_id,
        "title": m.title,
        "root_node_id": m.root_node_id,
        "viewport_state": m.viewport_state or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------
def _parents_first(nodes: List[MindMapNode]) -> List[MindMapNode]:
    """Order nodes so every parent precedes its children.

    Copies are inserted with `parent_id` already set, and foreign keys are
    enforced (PRAGMA foreign_keys=ON), so inserting a child before its parent
    fails. SQLAlchemy flushes in arbitrary order, so we impose one here.
    """
    by_parent: Dict[Optional[str], List[MindMapNode]] = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    known = {n.id for n in nodes}
    ordered: List[MindMapNode] = []
    # Roots of this set: no parent, or a parent outside the set.
    queue = [n for n in nodes if n.parent_id is None or n.parent_id not in known]
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        queue.extend(by_parent.get(node.id, []))

    # Any node left over is part of a cycle; append it so nothing is silently lost.
    if len(ordered) < len(nodes):
        seen = {n.id for n in ordered}
        ordered.extend(n for n in nodes if n.id not in seen)
    return ordered


def create_map(db: DatabaseManager, project_id: str, title: str,
               session_id: Optional[str] = None, with_root: bool = True) -> Dict[str, Any]:
    map_id = str(uuid.uuid4())
    with db.get_session() as s:
        m = MindMap(id=map_id, project_id=project_id, title=title, session_id=session_id)
        s.add(m)
        if with_root:
            root_id = str(uuid.uuid4())
            s.add(MindMapNode(
                id=root_id, mind_map_id=map_id, project_id=project_id,
                parent_id=None, title=title, node_type="Idea", sort_order=0,
                extra_metadata={"position": {"x": 0, "y": 0}},
            ))
            m.root_node_id = root_id
        s.commit()
        return map_dict(m)


def list_maps(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        maps = (
            s.query(MindMap)
            .filter(MindMap.project_id == project_id)
            .order_by(MindMap.updated_at.desc())
            .all()
        )
        return [map_dict(m) for m in maps]


def get_map(db: DatabaseManager, map_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        m = s.get(MindMap, map_id)
        return map_dict(m) if m else None


def update_map(db: DatabaseManager, map_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        m = s.get(MindMap, map_id)
        if not m:
            return None
        for k in ("title", "root_node_id", "viewport_state"):
            if changes.get(k) is not None:
                setattr(m, k, changes[k])
        m.updated_at = datetime.utcnow()
        s.commit()
        return map_dict(m)


def delete_map(db: DatabaseManager, map_id: str) -> bool:
    """Delete a map and everything in it. Never touches brainstorm content."""
    with db.get_session() as s:
        m = s.get(MindMap, map_id)
        if not m:
            return False
        s.query(MindMapEdge).filter(MindMapEdge.mind_map_id == map_id).delete()
        s.query(MindMapSnapshot).filter(MindMapSnapshot.mind_map_id == map_id).delete()
        s.query(MindMapNode).filter(MindMapNode.mind_map_id == map_id).delete()
        s.delete(m)
        s.commit()
        return True


def duplicate_map(db: DatabaseManager, map_id: str) -> Optional[Dict[str, Any]]:
    """Deep-copy a map: new IDs, same structure."""
    with db.get_session() as s:
        src = s.get(MindMap, map_id)
        if not src:
            return None
        nodes = s.query(MindMapNode).filter(MindMapNode.mind_map_id == map_id).all()
        edges = s.query(MindMapEdge).filter(MindMapEdge.mind_map_id == map_id).all()

        new_map_id = str(uuid.uuid4())
        id_map = {n.id: str(uuid.uuid4()) for n in nodes}

        s.add(MindMap(
            id=new_map_id, project_id=src.project_id, session_id=src.session_id,
            title=f"{src.title} (copy)",
            root_node_id=id_map.get(src.root_node_id) if src.root_node_id else None,
            viewport_state=src.viewport_state or {},
        ))
        for n in _parents_first(nodes):
            s.add(MindMapNode(
                id=id_map[n.id], mind_map_id=new_map_id, project_id=n.project_id,
                parent_id=id_map.get(n.parent_id) if n.parent_id else None,
                title=n.title, description=n.description, node_type=n.node_type,
                color=n.color, sort_order=n.sort_order, extra_metadata=n.extra_metadata or {},
            ))
            s.flush()  # keep the parent-before-child order the DB requires
        for e in edges:
            if e.source_node_id in id_map and e.target_node_id in id_map:
                s.add(MindMapEdge(
                    id=str(uuid.uuid4()), mind_map_id=new_map_id,
                    source_node_id=id_map[e.source_node_id],
                    target_node_id=id_map[e.target_node_id],
                    relation_type=e.relation_type,
                ))
        s.commit()
        return map_dict(s.get(MindMap, new_map_id))


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def create_node(db: DatabaseManager, map_id: str, title: str,
                parent_id: Optional[str] = None, node_type: str = "Idea",
                **kwargs: Any) -> Dict[str, Any]:
    with db.get_session() as s:
        m = s.get(MindMap, map_id)
        if not m:
            raise MindMapError("Mind map not found")
        if parent_id and not s.get(MindMapNode, parent_id):
            raise MindMapError("Parent node not found")

        siblings = (
            s.query(MindMapNode)
            .filter(MindMapNode.mind_map_id == map_id, MindMapNode.parent_id == parent_id)
            .count()
        )
        node = MindMapNode(
            id=str(uuid.uuid4()), mind_map_id=map_id, project_id=m.project_id,
            parent_id=parent_id, title=title, node_type=node_type,
            description=kwargs.get("description", ""), color=kwargs.get("color"),
            sort_order=kwargs.get("sort_order", siblings),
            extra_metadata=kwargs.get("metadata") or {},
        )
        s.add(node)
        if parent_id is None and not m.root_node_id:
            m.root_node_id = node.id
        m.updated_at = datetime.utcnow()
        s.commit()
        return node_dict(node)


def update_node(db: DatabaseManager, node_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        n = s.get(MindMapNode, node_id)
        if not n:
            return None
        for k in ("title", "description", "node_type", "color", "sort_order"):
            if changes.get(k) is not None:
                setattr(n, k, changes[k])
        if changes.get("metadata") is not None:
            # merge so a position update doesn't wipe priority/status
            n.extra_metadata = {**(n.extra_metadata or {}), **changes["metadata"]}
        n.updated_at = datetime.utcnow()
        s.commit()
        return node_dict(n)


def _would_cycle(s, node_id: str, new_parent_id: Optional[str]) -> bool:
    """True if re-parenting node under new_parent would create a cycle."""
    if new_parent_id is None:
        return False
    if new_parent_id == node_id:
        return True
    seen = set()
    cur = s.get(MindMapNode, new_parent_id)
    while cur is not None:
        if cur.id == node_id:
            return True
        if cur.id in seen:  # pre-existing corruption; stop rather than loop
            return True
        seen.add(cur.id)
        cur = s.get(MindMapNode, cur.parent_id) if cur.parent_id else None
    return False


def move_node(db: DatabaseManager, node_id: str, new_parent_id: Optional[str],
              sort_order: Optional[int] = None) -> Dict[str, Any]:
    with db.get_session() as s:
        n = s.get(MindMapNode, node_id)
        if not n:
            raise MindMapError("Node not found")
        if new_parent_id:
            parent = s.get(MindMapNode, new_parent_id)
            if not parent:
                raise MindMapError("Target parent not found")
            if parent.mind_map_id != n.mind_map_id:
                raise MindMapError("Cannot move a node into a different map")
        if _would_cycle(s, node_id, new_parent_id):
            raise MindMapError("That move would create a cycle")

        n.parent_id = new_parent_id
        if sort_order is not None:
            n.sort_order = sort_order
        n.updated_at = datetime.utcnow()
        s.commit()
        return node_dict(n)


def _descendants(s, node_id: str) -> List[str]:
    out, stack = [], [node_id]
    while stack:
        cur = stack.pop()
        for child in s.query(MindMapNode).filter(MindMapNode.parent_id == cur).all():
            out.append(child.id)
            stack.append(child.id)
    return out


def delete_node(db: DatabaseManager, node_id: str) -> int:
    """Delete a node and its descendants. Returns how many were removed."""
    with db.get_session() as s:
        n = s.get(MindMapNode, node_id)
        if not n:
            return 0
        ids = [node_id] + _descendants(s, node_id)
        s.query(MindMapEdge).filter(
            (MindMapEdge.source_node_id.in_(ids)) | (MindMapEdge.target_node_id.in_(ids))
        ).delete(synchronize_session=False)
        s.query(MindMapNode).filter(MindMapNode.id.in_(ids)).delete(synchronize_session=False)
        s.commit()
        return len(ids)


def duplicate_node(db: DatabaseManager, node_id: str) -> Optional[Dict[str, Any]]:
    """Copy a node and its whole subtree under the same parent."""
    with db.get_session() as s:
        src = s.get(MindMapNode, node_id)
        if not src:
            return None
        ids = [node_id] + _descendants(s, node_id)
        nodes = s.query(MindMapNode).filter(MindMapNode.id.in_(ids)).all()
        id_map = {n.id: str(uuid.uuid4()) for n in nodes}
        for n in _parents_first(nodes):
            s.add(MindMapNode(
                id=id_map[n.id], mind_map_id=n.mind_map_id, project_id=n.project_id,
                parent_id=(src.parent_id if n.id == node_id else id_map.get(n.parent_id)),
                title=(f"{n.title} (copy)" if n.id == node_id else n.title),
                description=n.description, node_type=n.node_type, color=n.color,
                sort_order=(n.sort_order or 0) + 1,
                extra_metadata=n.extra_metadata or {},
            ))
            s.flush()  # keep the parent-before-child order the DB requires
        s.commit()
        return node_dict(s.get(MindMapNode, id_map[node_id]))


# ---------------------------------------------------------------------------
# Tree, edges, snapshots, validation
# ---------------------------------------------------------------------------
def get_map_tree(db: DatabaseManager, map_id: str) -> Optional[Dict[str, Any]]:
    """The whole map in one payload: map + nested nodes + cross-branch edges."""
    with db.get_session() as s:
        m = s.get(MindMap, map_id)
        if not m:
            return None
        nodes = s.query(MindMapNode).filter(MindMapNode.mind_map_id == map_id).all()
        edges = s.query(MindMapEdge).filter(MindMapEdge.mind_map_id == map_id).all()

    by_id = {n.id: {**node_dict(n), "children": []} for n in nodes}
    roots: List[Dict[str, Any]] = []
    for n in nodes:
        entry = by_id[n.id]
        parent = by_id.get(n.parent_id) if n.parent_id else None
        (parent["children"] if parent else roots).append(entry)
    for entry in by_id.values():
        entry["children"].sort(key=lambda c: c["sort_order"])
    roots.sort(key=lambda c: c["sort_order"])

    return {
        "map": map_dict(m),
        "nodes": roots,
        "flat": [node_dict(n) for n in nodes],
        "edges": [
            {"id": e.id, "source_node_id": e.source_node_id,
             "target_node_id": e.target_node_id, "relation_type": e.relation_type}
            for e in edges
        ],
    }


def create_edge(db: DatabaseManager, map_id: str, source_id: str, target_id: str,
                relation_type: str = "related") -> Dict[str, Any]:
    if source_id == target_id:
        raise MindMapError("An edge must connect two different nodes")
    with db.get_session() as s:
        for nid in (source_id, target_id):
            if not s.get(MindMapNode, nid):
                raise MindMapError("Edge endpoint not found")
        e = MindMapEdge(id=str(uuid.uuid4()), mind_map_id=map_id,
                        source_node_id=source_id, target_node_id=target_id,
                        relation_type=relation_type)
        s.add(e)
        s.commit()
        return {"id": e.id, "source_node_id": source_id, "target_node_id": target_id,
                "relation_type": relation_type}


def delete_edge(db: DatabaseManager, edge_id: str) -> bool:
    with db.get_session() as s:
        e = s.get(MindMapEdge, edge_id)
        if not e:
            return False
        s.delete(e)
        s.commit()
        return True


def save_snapshot(db: DatabaseManager, map_id: str, snapshot: Dict[str, Any],
                  label: str = "") -> str:
    snap_id = str(uuid.uuid4())
    with db.get_session() as s:
        s.add(MindMapSnapshot(id=snap_id, mind_map_id=map_id,
                              snapshot_json=json.dumps(snapshot), operation_label=label))
        s.commit()
    return snap_id


def list_snapshots(db: DatabaseManager, map_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        snaps = (
            s.query(MindMapSnapshot)
            .filter(MindMapSnapshot.mind_map_id == map_id)
            .order_by(MindMapSnapshot.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {"id": x.id, "label": x.operation_label,
             "created_at": x.created_at.isoformat() if x.created_at else None}
            for x in snaps
        ]


def validate_tree(db: DatabaseManager, map_id: str) -> List[Dict[str, str]]:
    """Structural integrity check: orphans, bad parents, cycles."""
    problems: List[Dict[str, str]] = []
    with db.get_session() as s:
        nodes = s.query(MindMapNode).filter(MindMapNode.mind_map_id == map_id).all()
        ids = {n.id for n in nodes}
        for n in nodes:
            if n.parent_id and n.parent_id not in ids:
                problems.append({"node_id": n.id, "issue": "invalid_parent",
                                 "message": f"'{n.title}' points at a missing parent"})
        # cycle detection by walking up from each node
        parent_of = {n.id: n.parent_id for n in nodes}
        for n in nodes:
            seen, cur = set(), n.id
            while cur:
                if cur in seen:
                    problems.append({"node_id": n.id, "issue": "cycle",
                                     "message": f"'{n.title}' is part of a cycle"})
                    break
                seen.add(cur)
                cur = parent_of.get(cur)
    return problems
