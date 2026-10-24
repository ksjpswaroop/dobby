"""
Markdown-outline interchange for mind maps.

This is the format that lets a Dobby map leave the app and come back. Heading
markdown (`#` / `##` / `###`) is the closest thing to a lingua franca for
mind-mapping tools — markmap, Obsidian's outline view, Logseq, Mind Map Wizard
and most "text to mind map" generators all speak it — so a map exported here
opens elsewhere, and an outline written elsewhere imports here.

Why headings rather than our older nested-bullet markdown: bullets encode depth
as *indentation*, which every editor renders differently and which breaks the
moment someone reflows a paragraph. Headings encode depth as an explicit level
that survives copy-paste through chat windows, email, and terminals. The parser
still accepts bullets, because real-world outlines mix both.

Round-trip guarantee: ``parse_outline(to_outline(tree))`` reproduces the same
titles, hierarchy, descriptions and checked state. Node ids and cross-links do
not survive — those need the JSON format, which stays the lossless one.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from src.db.mindmap_models import MindMap, MindMapNode
from src.db.schema import DatabaseManager
from src.services import mindmap_service as svc

logger = structlog.get_logger()

MAX_HEADING = 6      # markdown stops at h6; deeper levels become bullets
MAX_DEPTH = 12       # a runaway paste shouldn't build an unbounded tree
MAX_NODES = 2000     # nor an unbounded number of nodes

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_CHECKBOX = re.compile(r"^\[([ xX])\]\s*")
_FENCE = re.compile(r"^\s*(```|~~~)")
# Trailing detail after a dash: `**Title** — description`. Only dash forms are
# treated as a split, because a colon is far more often part of the title
# itself ("Education: PhD in Physics").
_DETAIL = re.compile(r"\s+(?:—|–|--)\s+(.*)$")


def _clean(text: str) -> str:
    """Strip inline markdown emphasis and links down to plain text."""
    text = text.strip()
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)   # [label](url) -> label
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)         # bold
    text = re.sub(r"(?<!\w)([*_])(.+?)\1(?!\w)", r"\2", text)  # italic
    text = re.sub(r"`([^`]+)`", r"\1", text)                # code
    return text.strip()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def to_outline(tree: Dict[str, Any]) -> str:
    """Render a map tree as heading markdown."""
    lines: List[str] = [f"# {_clean(tree['map']['title']) or 'Mind map'}", ""]

    def emit(nodes: List[Dict[str, Any]], depth: int) -> None:
        for n in nodes:
            title = _clean(n.get("title") or "") or "Untitled"
            # Checked state rides along as a task marker. Unchecked nodes emit
            # nothing, so a map nobody uses checkboxes on stays clean for other
            # tools rather than being littered with `[ ]`.
            mark = "[x] " if (n.get("metadata") or {}).get("checked") else ""
            desc = _clean(n.get("description") or "")

            level = depth + 1
            if level <= MAX_HEADING:
                lines.append(f"{'#' * level} {mark}{title}")
                if desc:
                    lines.append("")
                    lines.append(desc)
                lines.append("")
            else:
                indent = "  " * (level - MAX_HEADING - 1)
                detail = f" — {desc}" if desc else ""
                lines.append(f"{indent}- {mark}{title}{detail}")

            emit(n.get("children") or [], depth + 1)

    for root in tree.get("nodes") or []:
        emit(root.get("children") or [], 1)

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------
def parse_outline(text: str) -> Dict[str, Any]:
    """Parse heading/bullet markdown into ``{"title", "children"}``.

    Deliberately forgiving: outlines arrive pasted from chat windows, LLM
    output, and other apps, so anything unrecognisable becomes description text
    on the current node rather than an error. The only hard failure is an
    outline with no nodes at all, which the caller can report usefully.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The outline is empty.")

    title: Optional[str] = None
    roots: List[Dict[str, Any]] = []
    # Open ancestors as (source_depth, node). Tracking the *source* depth is
    # what makes skipped levels work: an outline that jumps `#` -> `###` and
    # then back to `###` must treat both h3s as siblings, which a
    # position-indexed stack gets wrong.
    stack: List[tuple[int, Dict[str, Any]]] = []
    count = 0
    in_fence = False
    # Depth of the last heading, so bullets nest beneath it rather than at
    # top level — bullets under `### Foo` belong to Foo.
    heading_depth = 0

    def new_node(raw: str) -> Optional[Dict[str, Any]]:
        nonlocal count
        if count >= MAX_NODES:
            return None
        body = raw.strip()
        checked = False
        m = _CHECKBOX.match(body)
        if m:
            checked = m.group(1).lower() == "x"
            body = body[m.end():]

        description = ""
        d = _DETAIL.search(body)
        if d:
            description = _clean(d.group(1))
            body = body[: d.start()]

        name = _clean(body)
        if not name:
            return None

        count += 1
        return {
            "title": name[:200],
            "description": description[:2000],
            "checked": checked,
            "children": [],
        }

    def attach(node: Dict[str, Any], depth: int) -> None:
        depth = max(1, min(depth, MAX_DEPTH))
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((depth, node))

    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue

        h = _HEADING.match(line)
        if h:
            level = len(h.group(1))
            if level == 1 and title is None and not roots:
                # The first h1 names the map itself. Later h1s are branches —
                # some tools emit every branch as h1.
                parsed = new_node(h.group(2))
                if parsed:
                    title = parsed["title"]
                    count -= 1  # the map title is not a node
                continue
            depth = max(1, level - 1)
            node = new_node(h.group(2))
            if node:
                attach(node, depth)
                heading_depth = depth
            continue

        b = _BULLET.match(line)
        if b:
            # Two spaces (or one tab) per level, matching how editors indent.
            indent = b.group(1).replace("\t", "  ")
            depth = heading_depth + 1 + len(indent) // 2
            node = new_node(b.group(2))
            if node:
                attach(node, depth)
            continue

        # Plain prose describes whichever node is currently open.
        if stack:
            existing = stack[-1][1]["description"]
            extra = _clean(line)
            if extra and len(existing) < 2000:
                stack[-1][1]["description"] = (f"{existing} {extra}".strip())[:2000]

    if not roots:
        raise ValueError(
            "No headings or bullets found. Use '# Title' then '## Branch', "
            "or an indented '- ' list."
        )

    return {"title": (title or roots[0]["title"])[:200], "children": roots}


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------
def _write_children(db: DatabaseManager, map_id: str, parent_id: Optional[str],
                    children: List[Dict[str, Any]], depth: int = 0) -> int:
    created = 0
    for child in children:
        node = svc.create_node(
            db, map_id, child["title"], parent_id, "Idea",
            description=child.get("description", ""),
        )
        if child.get("checked"):
            svc.update_node(db, node["id"], metadata={"checked": True})
        created += 1 + _write_children(
            db, map_id, node["id"], child.get("children") or [], depth + 1
        )
    return created


def import_outline(db: DatabaseManager, project_id: str, text: str,
                   title: Optional[str] = None) -> Dict[str, Any]:
    """Create a new map from pasted or uploaded outline markdown."""
    parsed = parse_outline(text)
    map_title = (title or parsed["title"])[:200]
    new_map = svc.create_map(db, project_id, map_title)
    created = _write_children(db, new_map["id"], new_map["root_node_id"], parsed["children"])
    logger.info("mindmap_outline_imported", map_id=new_map["id"], nodes=created)
    return {"success": True, "map_id": new_map["id"], "title": map_title,
            "nodes_imported": created}


def replace_from_outline(db: DatabaseManager, map_id: str, text: str,
                         reason: str = "before outline edit") -> Dict[str, Any]:
    """Rewrite an existing map's contents from an outline, snapshotting first.

    Used by both the outline editor and AI chat editing, so an unwanted change
    is always one undo away.
    """
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        return {"success": False, "error": "Mind map not found"}

    parsed = parse_outline(text)
    svc.save_snapshot(db, map_id, tree, reason)

    root_id = tree["map"].get("root_node_id")
    for node in tree["flat"]:
        if node["id"] != root_id:
            svc.delete_node(db, node["id"])

    if parsed["title"]:
        svc.update_map(db, map_id, title=parsed["title"])
        if root_id:
            svc.update_node(db, root_id, title=parsed["title"])

    created = _write_children(db, map_id, root_id, parsed["children"])
    return {"success": True, "nodes_created": created}
