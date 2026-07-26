"""
Mind-map export & import.

Formats:
* **JSON** — the round-trip format; export then import reproduces the map.
* **Markdown** — an indented outline, for pasting into docs.
* **Mermaid** — `mindmap` syntax, so a map can be embedded anywhere Mermaid renders.

PNG/SVG are deliberately *not* here: the visual is a client-side render, so the
frontend exports the live canvas. The backend supplies structure; the browser
supplies pixels.

Markdown and Mermaid shapes follow the conventions in the mindmap-skill
reference (`export-patterns.md`), including stripping bracket characters that
would otherwise break Mermaid node labels.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.db.mindmap_models import MindMap, MindMapEdge, MindMapNode
from src.db.schema import DatabaseManager
from src.services import mindmap_service as svc

logger = structlog.get_logger()

EXPORT_VERSION = 1


class ImportError_(Exception):
    """Invalid import payload — carries a field-level message for the user."""


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def export_json(db: DatabaseManager, map_id: str) -> Dict[str, Any]:
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        raise ImportError_("Mind map not found")
    return {
        "format": "dobby.mindmap",
        "version": EXPORT_VERSION,
        "map": {"title": tree["map"]["title"]},
        "nodes": tree["flat"],
        "edges": tree["edges"],
    }


def export_markdown(db: DatabaseManager, map_id: str) -> str:
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        raise ImportError_("Mind map not found")

    lines: List[str] = [f"# {tree['map']['title']}", ""]

    def walk(nodes: List[Dict[str, Any]], depth: int) -> None:
        for n in nodes:
            if depth == 0:
                lines.append(f"## {n['title']}")
                if n.get("description"):
                    lines.append("")
                    lines.append(n["description"])
                lines.append("")
            else:
                indent = "  " * (depth - 1)
                detail = f" — {n['description']}" if n.get("description") else ""
                lines.append(f"{indent}- **{n['title']}**{detail}")
            walk(n.get("children") or [], depth + 1)
            if depth == 0:
                lines.append("")

    # The root node is the document title; its children are the top-level sections.
    roots = tree["nodes"]
    for root in roots:
        walk(root.get("children") or [], 0)

    if tree["edges"]:
        by_id = {n["id"]: n["title"] for n in tree["flat"]}
        lines.append("## Cross-links")
        lines.append("")
        for e in tree["edges"]:
            src = by_id.get(e["source_node_id"], "?")
            dst = by_id.get(e["target_node_id"], "?")
            lines.append(f"- {src} → {dst} ({e.get('relation_type', 'related')})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _mermaid_label(text: str) -> str:
    """Strip characters that break Mermaid node labels."""
    return re.sub(r"[()\[\]{}]", "", text).strip() or "untitled"


def export_mermaid(db: DatabaseManager, map_id: str) -> str:
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        raise ImportError_("Mind map not found")

    title = _mermaid_label(tree["map"]["title"])
    lines: List[str] = ["mindmap", f"  root(({title}))"]

    def walk(nodes: List[Dict[str, Any]], depth: int) -> None:
        for n in nodes:
            lines.append("  " * (depth + 2) + _mermaid_label(n["title"]))
            walk(n.get("children") or [], depth + 1)

    for root in tree["nodes"]:
        walk(root.get("children") or [], 0)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def import_json(db: DatabaseManager, project_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new map from an exported payload.

    Validation is field-level and user-facing: an import that fails should say
    *what* is wrong, not just that it is.
    """
    if not isinstance(data, dict):
        raise ImportError_("The file must contain a JSON object.")
    if data.get("format") not in (None, "dobby.mindmap"):
        raise ImportError_(f"Unsupported format: {data.get('format')!r}.")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ImportError_("Missing 'nodes': the file has no nodes to import.")

    title = (data.get("map") or {}).get("title") or "Imported map"

    # Validate each node before writing anything.
    seen_ids = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            raise ImportError_(f"nodes[{i}] is not an object.")
        if not str(n.get("title") or "").strip():
            raise ImportError_(f"nodes[{i}] is missing a title.")
        nid = n.get("id")
        if not nid:
            raise ImportError_(f"nodes[{i}] is missing an id.")
        if nid in seen_ids:
            raise ImportError_(f"Duplicate node id: {nid}.")
        seen_ids.add(nid)

    for i, n in enumerate(nodes):
        parent = n.get("parent_id")
        if parent and parent not in seen_ids:
            raise ImportError_(f"nodes[{i}] ('{n['title']}') points at a missing parent.")
        if parent == n["id"]:
            raise ImportError_(f"nodes[{i}] ('{n['title']}') is its own parent.")

    # Reject cycles up front — a cyclic import would corrupt the tree.
    parent_of = {n["id"]: n.get("parent_id") for n in nodes}
    for nid in parent_of:
        slow, fast = nid, nid
        while fast and parent_of.get(fast):
            slow = parent_of[slow]
            fast = parent_of.get(parent_of.get(fast))
            if fast and slow == fast:
                raise ImportError_("The file contains a cycle in the node hierarchy.")

    # Fresh ids so an import never collides with an existing map.
    id_map = {n["id"]: str(uuid.uuid4()) for n in nodes}
    new_map = svc.create_map(db, project_id, title, with_root=False)
    map_id = new_map["id"]

    ordered: List[Dict[str, Any]] = []
    children_of: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for n in nodes:
        children_of.setdefault(n.get("parent_id"), []).append(n)
    queue = [n for n in nodes if not n.get("parent_id")]
    while queue:
        cur = queue.pop(0)
        ordered.append(cur)
        queue.extend(children_of.get(cur["id"], []))

    with db.get_session() as s:
        for n in ordered:
            s.add(MindMapNode(
                id=id_map[n["id"]], mind_map_id=map_id, project_id=project_id,
                parent_id=id_map.get(n.get("parent_id")) if n.get("parent_id") else None,
                title=str(n["title"])[:200],
                description=str(n.get("description") or "")[:2000],
                node_type=n.get("node_type") if n.get("node_type") in svc.NODE_TYPES else "Idea",
                color=n.get("color"), sort_order=int(n.get("sort_order") or 0),
                extra_metadata=n.get("metadata") or {},
            ))
            s.flush()  # parents before children, for the FK
        for e in data.get("edges") or []:
            src, dst = id_map.get(e.get("source_node_id")), id_map.get(e.get("target_node_id"))
            if src and dst:
                s.add(MindMapEdge(
                    id=str(uuid.uuid4()), mind_map_id=map_id,
                    source_node_id=src, target_node_id=dst,
                    relation_type=e.get("relation_type", "related"),
                ))
        # Point the map at its (new) root.
        root = next((n for n in ordered if not n.get("parent_id")), None)
        if root:
            m = s.get(MindMap, map_id)
            if m:
                m.root_node_id = id_map[root["id"]]
        s.commit()

    logger.info("mindmap_imported", map_id=map_id, nodes=len(ordered))
    return {"success": True, "map_id": map_id, "nodes_imported": len(ordered)}
