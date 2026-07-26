"""
Mind-map AI — generate, expand, and regroup maps with the local model.

Design notes:

* **Source material.** The plan specced generating from `Session.state`, but the
  richer, always-present context in this app is the project itself: its idea,
  its backlog features, and its generated feature nodes. We build from those and
  fall back to the map's own title when a project is empty.
* **Small models produce bad JSON.** That was flagged as launch-blocking, so
  every call is two-pass: first with Ollama's `format="json"`, and on a parse or
  schema failure the raw output is handed back to the model to repair. A second
  failure returns a structured error — it never raises into the UI.
* **Nothing is silently overwritten.** `regroup` only *proposes*; applying it
  saves a snapshot of the previous tree first.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.db.mindmap_models import MindMap, MindMapNode
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project
from src.llm.ollama_client import get_ollama_client
from src.services import mindmap_service as svc

logger = structlog.get_logger()

MAX_DEPTH = 4
MAX_CHILDREN = 12

SCHEMA_HINT = """Return ONLY JSON in exactly this shape:
{
  "title": "<title of the whole map>",
  "children": [
    {"title": "<name of a theme>", "node_type": "Idea", "description": "<one line>",
     "children": [{"title": "<a specific idea>", "node_type": "Feature", "description": "<one line>"}]}
  ]
}
Every <...> is a PLACEHOLDER: replace it with real content about the subject.
Never output the words "Theme", "Specific idea", or any <...> text literally.
node_type must be one of: %s.
No prose, no markdown fences — JSON only.""" % ", ".join(svc.NODE_TYPES)

# What separates a useful map from a table of contents. These are craft rules
# for mind mapping generally — concrete over categorical, breadth over depth,
# no essay scaffolding — written for our schema and our node types.
QUALITY_RULES = """Rules:
- 4 to 6 top-level themes, each a genuinely different aspect of the subject.
- Every theme MUST have a non-empty "children" array with 2-4 entries.
- Two to three levels deep. A mind map is for scanning, not for reading.
- Titles carry facts, not category labels. Prefer "Rent: under $3k downtown"
  to "Location". A title that could head any map about any subject is wrong.
- Skip essay scaffolding: no "Overview", "Introduction", "Summary",
  "Conclusion", or "Other".
- When a theme would need six or more siblings, combine related ones into a
  single comma-separated entry rather than fanning out.
- Branches need not be the same size. Say more where there is more to say.
- Keep titles under 8 words, and write in the language of the subject.
- Everything must be about the subject. Do not copy unrelated examples."""

# Titles a model produces when it copies the schema instead of following it.
_PLACEHOLDER_TITLES = {
    "theme", "specific idea", "another specific idea", "title", "name of a theme",
    "a specific idea", "child", "children", "node", "idea 1", "idea 2", "example",
    "title of the whole map", "one line", "sub-theme", "subtheme", "item",
}


def _is_placeholder(title: str) -> bool:
    """True if the model echoed the schema rather than generating content."""
    t = title.strip().lower().strip(".:")
    if t in _PLACEHOLDER_TITLES:
        return True
    # Anything still wearing angle brackets came straight from the template.
    return t.startswith("<") and t.endswith(">")


class AIUnavailable(Exception):
    """Ollama is unreachable — surfaced as 503 rather than a crash."""


# ---------------------------------------------------------------------------
# JSON handling
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull a JSON object out of a model response, fences and preamble included."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} span.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _coerce_tree(data: Any, depth: int = 0) -> List[Dict[str, Any]]:
    """Validate + normalize the model's children into our node shape.

    Anything malformed is dropped rather than rejected wholesale: a mostly-good
    tree is far more useful to a user than an error.
    """
    if not isinstance(data, list) or depth >= MAX_DEPTH:
        return []
    out: List[Dict[str, Any]] = []
    for item in data[:MAX_CHILDREN]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title or _is_placeholder(title):
            continue  # drop schema echoes rather than saving them as real nodes
        node_type = str(item.get("node_type") or "Idea").strip()
        if node_type not in svc.NODE_TYPES:
            node_type = "Idea"
        out.append({
            "title": title[:120],
            "node_type": node_type,
            "description": str(item.get("description") or "")[:600],
            "children": _coerce_tree(item.get("children"), depth + 1),
        })
    return out


async def _generate_json(prompt: str, what: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Two-pass JSON generation: constrained decode, then a repair round."""
    from src.settings import get_settings

    s = get_settings()
    try:
        client = await get_ollama_client(base_url=s.ollama_host, model=s.model)
    except Exception as e:
        raise AIUnavailable(str(e))

    try:
        raw = await client.generate(prompt, format="json", max_tokens=2000, temperature=0.6)
        parsed = _extract_json(raw)
        if parsed is not None:
            return parsed, None

        logger.warning("mindmap_ai_json_retry", what=what)
        repair = (
            "The following was supposed to be JSON but could not be parsed. "
            "Return the corrected JSON only, nothing else.\n\n"
            f"{raw[:3000]}\n\n{SCHEMA_HINT}"
        )
        raw2 = await client.generate(repair, format="json", max_tokens=2000, temperature=0.2)
        parsed = _extract_json(raw2)
        if parsed is not None:
            return parsed, None

        return None, f"The model did not return valid JSON for {what}. Try again, or use a larger model."
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def _project_context(db: DatabaseManager, project_id: str, limit: int = 25) -> str:
    """A compact summary of the project for grounding generation."""
    lines: List[str] = []
    with db.get_session() as s:
        project = s.get(Project, project_id)
        if project:
            lines.append(f"Project: {project.name}")
            if project.idea:
                lines.append(f"Idea: {project.idea}")

        features = (
            s.query(FeatureBacklog)
            .filter(FeatureBacklog.project_id == project_id)
            .order_by(FeatureBacklog.pareto_score.desc())
            .limit(limit)
            .all()
        )
        if features:
            lines.append("\nBacklog features (highest value first):")
            lines.extend(f"- {f.title}: {(f.description or '')[:140]}" for f in features)

        nodes = (
            s.query(Node)
            .filter(Node.project_id == project_id, Node.node_type == "feature")
            .limit(limit)
            .all()
        )
        if nodes:
            lines.append("\nFeatures already documented:")
            lines.extend(f"- {n.title}" for n in nodes)

    return "\n".join(lines).strip()


def _persist_children(db: DatabaseManager, map_id: str, parent_id: Optional[str],
                      children: List[Dict[str, Any]]) -> int:
    """Insert a generated subtree, parents before children."""
    created = 0
    for child in children:
        node = svc.create_node(
            db, map_id, child["title"], parent_id, child["node_type"],
            description=child.get("description", ""),
        )
        created += 1
        created += _persist_children(db, map_id, node["id"], child.get("children") or [])
    return created


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------
async def generate_map(db: DatabaseManager, project_id: str,
                       topic: Optional[str] = None) -> Dict[str, Any]:
    """Build a whole new map from the project's context (or an explicit topic)."""
    context = _project_context(db, project_id)

    if topic:
        # An explicit topic wins. Feeding the backlog in alongside it makes small
        # models parrot existing feature titles instead of exploring the topic,
        # so the project context is deliberately left out here.
        subject = topic
        context_block = ""
    else:
        subject = context.splitlines()[0] if context else "this product"
        context_block = f"Context about the project:\n{context}\n\n" if context else ""

    prompt = (
        "You are an expert product strategist building a mind map about a subject.\n\n"
        f"SUBJECT: {subject}\n\n"
        f"{context_block}"
        f"Build a mind map about the SUBJECT above — \"{subject}\".\n"
        f"{QUALITY_RULES}\n"
        f"{SCHEMA_HINT}"
    )

    parsed, error = await _generate_json(prompt, "the mind map")
    if error:
        return {"success": False, "error": error}

    children = _coerce_tree(parsed.get("children"))
    if not children:
        return {"success": False,
                "error": "The model returned no usable nodes. Try again, or use a larger model."}

    title = str(parsed.get("title") or subject)[:120]
    new_map = svc.create_map(db, project_id, title)
    created = _persist_children(db, new_map["id"], new_map["root_node_id"], children)

    logger.info("mindmap_ai_generated", map_id=new_map["id"], nodes=created)
    return {"success": True, "map_id": new_map["id"], "title": title, "nodes_created": created}


async def expand_node(db: DatabaseManager, node_id: str) -> Dict[str, Any]:
    """Generate 3-8 child ideas beneath an existing node."""
    with db.get_session() as s:
        node = s.get(MindMapNode, node_id)
        if not node:
            return {"success": False, "error": "Node not found"}
        map_id = node.mind_map_id
        title, description, node_type = node.title, node.description, node.node_type
        parent = s.get(MindMapNode, node.parent_id) if node.parent_id else None
        parent_title = parent.title if parent else None
        siblings = [
            n.title for n in
            s.query(MindMapNode).filter(MindMapNode.parent_id == node.parent_id).all()
            if n.id != node_id
        ]
        m = s.get(MindMap, map_id)
        project_id = m.project_id if m else None

    prompt = (
        "You are expanding one branch of a mind map.\n\n"
        f"Map subject: {_project_context(db, project_id).splitlines()[0] if project_id else ''}\n"
        f"Node to expand: {title} ({node_type})\n"
        f"{'Description: ' + description if description else ''}\n"
        f"{'Its parent: ' + parent_title if parent_title else ''}\n"
        f"{'Sibling nodes (do not repeat these): ' + ', '.join(siblings[:10]) if siblings else ''}\n\n"
        f"Generate 3 to 6 specific child ideas that belong under \"{title}\". "
        "Each must be a real, concrete idea about that topic — not a generic "
        "label. Do not restate the node itself, and give each an empty "
        "\"children\" array.\n\n"
        f"{SCHEMA_HINT}"
    )

    parsed, error = await _generate_json(prompt, "the expansion")
    if error:
        return {"success": False, "error": error}

    children = _coerce_tree(parsed.get("children"))[:8]
    if not children:
        return {"success": False, "error": "The model suggested no usable child ideas."}

    created = _persist_children(db, map_id, node_id, children)
    return {"success": True, "nodes_created": created}


async def regroup_map(db: DatabaseManager, map_id: str) -> Dict[str, Any]:
    """Propose a reorganization. Persists nothing — the user decides."""
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        return {"success": False, "error": "Mind map not found"}

    def outline(nodes: List[Dict[str, Any]], depth: int = 0) -> List[str]:
        rows: List[str] = []
        for n in nodes:
            rows.append(f"{'  ' * depth}- {n['title']} ({n['node_type']})")
            rows.extend(outline(n.get("children") or [], depth + 1))
        return rows

    current = "\n".join(outline(tree["nodes"]))
    prompt = (
        "Reorganize this mind map for clarity. Merge duplicates, group related "
        "ideas under better themes, and rename vague nodes. Keep all the "
        "substance — do not invent unrelated content.\n\n"
        f"Current map:\n{current}\n\n{SCHEMA_HINT}"
    )

    parsed, error = await _generate_json(prompt, "the regrouped map")
    if error:
        return {"success": False, "error": error}

    proposed = _coerce_tree(parsed.get("children"))
    if not proposed:
        return {"success": False, "error": "The model returned no usable structure."}

    def count(nodes: List[Dict[str, Any]]) -> int:
        return sum(1 + count(n.get("children") or []) for n in nodes)

    return {
        "success": True,
        "proposed": {"title": str(parsed.get("title") or tree["map"]["title"])[:120],
                     "children": proposed},
        "summary": {
            "current_nodes": len(tree["flat"]) - len(tree["nodes"]),
            "proposed_nodes": count(proposed),
        },
    }


async def chat_edit(db: DatabaseManager, map_id: str, instruction: str) -> Dict[str, Any]:
    """Apply a natural-language edit to a map: "drop the risks, expand marketing".

    Deliberately *not* JSON. Every other AI call here fights small local models
    for well-formed JSON and needs a repair round; editing is the one operation
    where we can sidestep that entirely, because the map has a faithful plain-text
    form. Markdown outline in, markdown outline out — a 1.5B model handles that
    reliably, and a partially-mangled outline still parses into a usable tree
    instead of failing wholesale.

    The edit applies immediately rather than being proposed: chat editing is an
    iterative loop, and `replace_from_outline` snapshots first, so undo is one
    click away.
    """
    from src.services import mindmap_outline as outline_svc

    instruction = (instruction or "").strip()
    if not instruction:
        return {"success": False, "error": "Say what you'd like changed."}

    tree = svc.get_map_tree(db, map_id)
    if not tree:
        return {"success": False, "error": "Mind map not found"}

    before = outline_svc.to_outline(tree)
    before_count = len(tree["flat"]) - len(tree["nodes"])

    prompt = (
        "You edit mind maps that are written as markdown outlines.\n\n"
        "CURRENT MIND MAP:\n"
        f"{before}\n"
        "INSTRUCTION FROM THE USER:\n"
        f"{instruction}\n\n"
        "Rewrite the whole outline with that instruction applied.\n"
        "Rules:\n"
        "- Output the COMPLETE outline, not just the part you changed.\n"
        "- Keep every heading level (`#`, `##`, `###`) exactly as markdown headings.\n"
        "- Keep the `# ` title line first.\n"
        "- Leave anything the instruction did not mention untouched.\n"
        "- Output the outline only. No commentary, no code fences.\n"
    )

    from src.settings import get_settings

    s = get_settings()
    try:
        client = await get_ollama_client(base_url=s.ollama_host, model=s.model)
    except Exception as e:
        raise AIUnavailable(str(e))
    try:
        raw = await client.generate(prompt, max_tokens=3000, temperature=0.3)
    finally:
        await client.close()

    text = re.sub(r"^\s*```(?:markdown|md)?\s*", "", (raw or "").strip())
    text = re.sub(r"\s*```\s*$", "", text)

    try:
        parsed = outline_svc.parse_outline(text)
    except ValueError:
        return {"success": False,
                "error": "The model didn't return a usable outline. Try rewording, "
                         "or use a larger model."}

    def count(nodes: List[Dict[str, Any]]) -> int:
        return sum(1 + count(n.get("children") or []) for n in nodes)

    after_count = count(parsed["children"])
    # A model that ignores "output the COMPLETE outline" and returns only the
    # edited fragment would silently destroy the rest of the map. Deletion is a
    # legitimate instruction, so only block the case where almost everything
    # vanished without being asked for.
    asked_to_remove = bool(re.search(
        r"\b(delete|remove|drop|prune|trim|clear|simplif|shorten|condense|fewer)",
        instruction, re.I))
    if before_count >= 5 and after_count < before_count * 0.4 and not asked_to_remove:
        return {"success": False,
                "error": f"The model returned only {after_count} of {before_count} nodes, "
                         "which would have deleted most of your map. Nothing was changed."}

    result = outline_svc.replace_from_outline(
        db, map_id, text, reason=f"before: {instruction[:60]}")
    if not result.get("success"):
        return result

    logger.info("mindmap_chat_edit", map_id=map_id, before=before_count, after=after_count)
    return {"success": True, "nodes_before": before_count, "nodes_after": after_count,
            "instruction": instruction}


def apply_regroup(db: DatabaseManager, map_id: str, proposed: Dict[str, Any]) -> Dict[str, Any]:
    """Replace a map's contents with an accepted proposal, snapshotting first."""
    tree = svc.get_map_tree(db, map_id)
    if not tree:
        return {"success": False, "error": "Mind map not found"}

    # Safety net: the previous structure is recoverable.
    svc.save_snapshot(db, map_id, tree, "before AI regroup")

    root_id = tree["map"].get("root_node_id")
    for node in tree["flat"]:
        if node["id"] != root_id and node["parent_id"] == root_id:
            svc.delete_node(db, node["id"])
    # any stragglers not under the root
    remaining = svc.get_map_tree(db, map_id)
    for node in remaining["flat"]:
        if node["id"] != root_id:
            svc.delete_node(db, node["id"])

    title = proposed.get("title")
    if title:
        svc.update_map(db, map_id, title=title)
        if root_id:
            svc.update_node(db, root_id, title=title)

    created = _persist_children(db, map_id, root_id, _coerce_tree(proposed.get("children")))
    return {"success": True, "nodes_created": created}
