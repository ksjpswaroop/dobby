"""
Living documents: editing, versioning, status, tags, comments.

The invariant everything else depends on: **no content change reaches a node
without a snapshot being written first.** `_snapshot()` is called by save,
section regeneration, refine, and restore alike, so "can I undo this?" has
one answer everywhere — yes.

Section handling parses Markdown ATX headings only (`#`..`######`). Fenced
code blocks are tracked while scanning so a `#` comment inside a shell
example is never mistaken for a heading, which would split a document at the
wrong place and make targeted regeneration overwrite the wrong text.
"""

from __future__ import annotations

import difflib
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.db.document_models import (
    DOC_STATUSES, STATUS_TRANSITIONS, VERSION_REASONS,
    Comment, DocumentMeta, DocumentType, NodeTag, NodeVersion, Tag,
)
from src.db.schema import DatabaseManager, Node, Project

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
WIKILINK_RE = re.compile(r"\[\[([^\[\]]{1,200})\]\]")


class DocumentError(Exception):
    pass


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def parse_sections(content: str) -> List[Dict[str, Any]]:
    """Split Markdown into heading-delimited sections.

    Text before the first heading becomes a preamble section with level 0, so
    every character of the document belongs to exactly one section and
    reassembly is lossless.
    """
    lines = (content or "").split("\n")
    sections: List[Dict[str, Any]] = []
    current = {"level": 0, "heading": "", "start_line": 0, "lines": []}
    in_fence = False

    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            if current["lines"] or current["heading"]:
                sections.append(current)
            current = {
                "level": len(m.group(1)),
                "heading": m.group(2),
                "start_line": i,
                "lines": [line],
            }
        else:
            current["lines"].append(line)

    if current["lines"] or current["heading"]:
        sections.append(current)

    out = []
    for idx, s in enumerate(sections):
        body = "\n".join(s["lines"])
        out.append({
            "index": idx,
            "level": s["level"],
            "heading": s["heading"],
            "text": body,
            "word_count": len(body.split()),
        })
    return out


def replace_section(content: str, index: int, new_text: str) -> str:
    sections = parse_sections(content)
    if index < 0 or index >= len(sections):
        raise DocumentError("That section no longer exists.")
    parts = [s["text"] for s in sections]
    parts[index] = new_text.rstrip()
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def _snapshot(s, node: Node, reason: str, note: str = "") -> NodeVersion:
    """Record the node's *current* state before it is changed."""
    if reason not in VERSION_REASONS:
        reason = "edit"
    latest = (s.query(NodeVersion)
              .filter(NodeVersion.node_id == node.id)
              .order_by(NodeVersion.version.desc())
              .first())
    version = (latest.version + 1) if latest else 1
    snap = NodeVersion(
        id=str(uuid.uuid4()), node_id=node.id, project_id=node.project_id,
        version=version, title=node.title, content=node.content or "",
        reason=reason, note=note[:300],
    )
    s.add(snap)
    return snap


def _meta(s, node: Node) -> DocumentMeta:
    meta = s.get(DocumentMeta, node.id)
    if not meta:
        meta = DocumentMeta(node_id=node.id, project_id=node.project_id,
                            status="draft", status_history=[])
        s.add(meta)
    return meta


def _version_dict(v: NodeVersion) -> Dict[str, Any]:
    return {
        "id": v.id, "version": v.version, "title": v.title,
        "reason": v.reason, "note": v.note,
        "word_count": len((v.content or "").split()),
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


def list_versions(db: DatabaseManager, node_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(NodeVersion)
                .filter(NodeVersion.node_id == node_id)
                .order_by(NodeVersion.version.desc()).all())
        return [_version_dict(v) for v in rows]


def get_version(db: DatabaseManager, version_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        v = s.get(NodeVersion, version_id)
        if not v:
            return None
        out = _version_dict(v)
        out["content"] = v.content
        return out


def diff_version(db: DatabaseManager, node_id: str, version_id: str) -> Dict[str, Any]:
    """Unified diff from a stored version to the node's current content."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        v = s.get(NodeVersion, version_id)
        if not node or not v or v.node_id != node_id:
            raise DocumentError("Version not found for this document.")
        old = (v.content or "").split("\n")
        new = (node.content or "").split("\n")
        hunks = list(difflib.unified_diff(
            old, new, fromfile=f"v{v.version}", tofile="current", lineterm="",
        ))
        added = sum(1 for l in hunks if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in hunks if l.startswith("-") and not l.startswith("---"))
        return {
            "version": v.version, "diff": hunks,
            "added_lines": added, "removed_lines": removed,
        }


def restore_version(db: DatabaseManager, node_id: str, version_id: str) -> Dict[str, Any]:
    """Restore prior content — itself snapshotted, so restore is undoable too."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        v = s.get(NodeVersion, version_id)
        if not node or not v or v.node_id != node_id:
            raise DocumentError("Version not found for this document.")
        _snapshot(s, node, "restore", note=f"before restoring v{v.version}")
        node.content = v.content
        node.title = v.title or node.title
        node.version = (node.version or 1) + 1
        node.updated_at = datetime.utcnow()
        meta = _meta(s, node)
        meta.dirty = 1
        s.commit()
        return get_document(db, node_id)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def get_document(db: DatabaseManager, node_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            return None
        meta = s.get(DocumentMeta, node_id)
        tag_rows = (s.query(Tag).join(NodeTag, NodeTag.tag_id == Tag.id)
                    .filter(NodeTag.node_id == node_id).all())
        version_count = (s.query(NodeVersion)
                         .filter(NodeVersion.node_id == node_id).count())
        open_comments = (s.query(Comment)
                         .filter(Comment.node_id == node_id, Comment.resolved == 0)
                         .count())
        content = node.content or ""
        return {
            "id": node.id,
            "project_id": node.project_id,
            "node_type": node.node_type,
            "title": node.title,
            "content": content,
            "word_count": len(content.split()),
            "status": meta.status if meta else "draft",
            "dirty": bool(meta.dirty) if meta else False,
            "status_history": (meta.status_history or []) if meta else [],
            "version_count": version_count,
            "open_comments": open_comments,
            "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tag_rows],
            "sections": [
                {k: v for k, v in sec.items() if k != "text"}
                for sec in parse_sections(content)
            ],
            "links": extract_wikilinks(content),
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        }


def save_content(db: DatabaseManager, node_id: str, content: str,
                 title: Optional[str] = None, reason: str = "edit",
                 note: str = "") -> Dict[str, Any]:
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentError("Document not found.")

        unchanged = (node.content or "") == content and (title is None or title == node.title)
        if unchanged:
            # Autosave fires on a timer; writing a snapshot per idle tick
            # would bury real edits in noise.
            return get_document(db, node_id)

        _snapshot(s, node, reason, note)
        node.content = content
        if title:
            node.title = title[:300]
        node.version = (node.version or 1) + 1
        node.updated_at = datetime.utcnow()
        meta = _meta(s, node)
        meta.dirty = 1
        s.commit()
    return get_document(db, node_id)


# ---------------------------------------------------------------------------
# Status workflow
# ---------------------------------------------------------------------------
def set_status(db: DatabaseManager, node_id: str, status: str) -> Dict[str, Any]:
    if status not in DOC_STATUSES:
        raise DocumentError(f"Unknown status. One of: {', '.join(DOC_STATUSES)}")
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentError("Document not found.")
        meta = _meta(s, node)
        current = meta.status or "draft"
        if status == current:
            s.commit()
            return get_document(db, node_id)
        if status not in STATUS_TRANSITIONS.get(current, ()):
            raise DocumentError(
                f"Cannot go from {current} to {status}. "
                f"Allowed: {', '.join(STATUS_TRANSITIONS.get(current, ())) or 'none'}"
            )
        now = datetime.utcnow()
        meta.status_history = list(meta.status_history or []) + [
            {"from": current, "to": status, "at": now.isoformat()}
        ]
        meta.status = status
        meta.status_changed_at = now
        s.commit()
    return get_document(db, node_id)


# ---------------------------------------------------------------------------
# Wiki links
# ---------------------------------------------------------------------------
def extract_wikilinks(content: str) -> List[str]:
    seen, out = set(), []
    for m in WIKILINK_RE.finditer(content or ""):
        title = m.group(1).strip()
        key = title.lower()
        if title and key not in seen:
            seen.add(key)
            out.append(title)
    return out


def resolve_links(db: DatabaseManager, project_id: str, node_id: str) -> Dict[str, Any]:
    """Map [[titles]] in a node to real nodes, and find who links back."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentError("Document not found.")
        titles = extract_wikilinks(node.content or "")

        by_title = {
            n.title.lower(): n
            for n in s.query(Node).filter(Node.project_id == project_id).all()
        }
        outgoing = [
            {"title": t,
             "node_id": by_title[t.lower()].id if t.lower() in by_title else None,
             "resolved": t.lower() in by_title}
            for t in titles
        ]

        # Backlinks: any node whose content links to this node's title.
        needle = (node.title or "").lower()
        backlinks = []
        if needle:
            for n in s.query(Node).filter(Node.project_id == project_id).all():
                if n.id == node_id:
                    continue
                if any(l.lower() == needle for l in extract_wikilinks(n.content or "")):
                    backlinks.append({"node_id": n.id, "title": n.title})

        return {"outgoing": outgoing, "backlinks": backlinks}


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def list_tags(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = s.query(Tag).filter(Tag.project_id == project_id).order_by(Tag.name).all()
        out = []
        for t in rows:
            count = s.query(NodeTag).filter(NodeTag.tag_id == t.id).count()
            out.append({"id": t.id, "name": t.name, "color": t.color, "count": count})
        return out


def add_tag(db: DatabaseManager, project_id: str, node_id: str,
            name: str, color: str = "neutral") -> Dict[str, Any]:
    name = (name or "").strip().lstrip("#")
    if not name:
        raise DocumentError("A tag needs a name.")
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise DocumentError("Project not found.")
        if not s.get(Node, node_id):
            raise DocumentError("Document not found.")
        tag = (s.query(Tag)
               .filter(Tag.project_id == project_id, Tag.name == name).first())
        if not tag:
            tag = Tag(id=str(uuid.uuid4()), project_id=project_id, name=name[:60], color=color)
            s.add(tag)
            s.flush()
        link = (s.query(NodeTag)
                .filter(NodeTag.node_id == node_id, NodeTag.tag_id == tag.id).first())
        if not link:
            s.add(NodeTag(id=str(uuid.uuid4()), node_id=node_id, tag_id=tag.id))
        s.commit()
    return get_document(db, node_id)


def remove_tag(db: DatabaseManager, node_id: str, tag_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        link = (s.query(NodeTag)
                .filter(NodeTag.node_id == node_id, NodeTag.tag_id == tag_id).first())
        if link:
            s.delete(link)
            s.commit()
    return get_document(db, node_id)


def find_by_tag(db: DatabaseManager, project_id: str, tag_name: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        tag = (s.query(Tag)
               .filter(Tag.project_id == project_id, Tag.name == tag_name.lstrip("#"))
               .first())
        if not tag:
            return []
        nodes = (s.query(Node).join(NodeTag, NodeTag.node_id == Node.id)
                 .filter(NodeTag.tag_id == tag.id).all())
        return [{"id": n.id, "title": n.title, "node_type": n.node_type} for n in nodes]


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
def _comment_dict(c: Comment) -> Dict[str, Any]:
    return {
        "id": c.id, "node_id": c.node_id, "parent_id": c.parent_id,
        "body": c.body, "start_offset": c.start_offset, "end_offset": c.end_offset,
        "anchor_text": c.anchor_text, "resolved": bool(c.resolved),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def add_comment(db: DatabaseManager, node_id: str, body: str,
                start_offset: Optional[int] = None, end_offset: Optional[int] = None,
                parent_id: Optional[str] = None) -> Dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise DocumentError("A comment needs a body.")
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentError("Document not found.")
        anchor = ""
        if start_offset is not None and end_offset is not None:
            anchor = (node.content or "")[start_offset:end_offset][:500]
        c = Comment(
            id=str(uuid.uuid4()), node_id=node_id, project_id=node.project_id,
            parent_id=parent_id, body=body[:4000],
            start_offset=start_offset, end_offset=end_offset, anchor_text=anchor,
        )
        s.add(c)
        s.commit()
        return _comment_dict(c)


def list_comments(db: DatabaseManager, node_id: str,
                  include_resolved: bool = True) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        q = s.query(Comment).filter(Comment.node_id == node_id)
        if not include_resolved:
            q = q.filter(Comment.resolved == 0)
        return [_comment_dict(c) for c in q.order_by(Comment.created_at).all()]


def set_comment_resolved(db: DatabaseManager, comment_id: str,
                         resolved: bool) -> Dict[str, Any]:
    with db.get_session() as s:
        c = s.get(Comment, comment_id)
        if not c:
            raise DocumentError("Comment not found.")
        c.resolved = 1 if resolved else 0
        s.commit()
        return _comment_dict(c)


def delete_comment(db: DatabaseManager, comment_id: str) -> bool:
    with db.get_session() as s:
        c = s.get(Comment, comment_id)
        if not c:
            return False
        # Replies would otherwise dangle with a parent_id pointing nowhere.
        # The flush matters: without it SQLAlchemy batches both deletes into a
        # single executemany whose order is not guaranteed, so the parent can
        # go first and trip the self-referential foreign key.
        for reply in s.query(Comment).filter(Comment.parent_id == comment_id).all():
            s.delete(reply)
        s.flush()
        s.delete(c)
        s.commit()
        return True


def reanchor_comments(db: DatabaseManager, node_id: str) -> int:
    """Re-find drifted anchors by content after an edit shifts offsets.

    Returns how many comments moved. A comment whose anchor text is simply
    gone keeps its old offsets and is reported as orphaned by the UI rather
    than being deleted — the note may still be the useful part.
    """
    moved = 0
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise DocumentError("Document not found.")
        content = node.content or ""
        for c in s.query(Comment).filter(Comment.node_id == node_id).all():
            if not c.anchor_text:
                continue
            at = content.find(c.anchor_text)
            if at >= 0 and at != c.start_offset:
                c.start_offset = at
                c.end_offset = at + len(c.anchor_text)
                moved += 1
        s.commit()
    return moved


# ---------------------------------------------------------------------------
# Custom document types
# ---------------------------------------------------------------------------
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:60]


def _type_dict(t: DocumentType) -> Dict[str, Any]:
    return {
        "id": t.id, "name": t.name, "slug": t.slug, "description": t.description,
        "sections": t.sections or [], "prompt": t.prompt,
        "verification_rules": t.verification_rules or {},
    }


def create_document_type(db: DatabaseManager, project_id: str, name: str,
                         sections: Optional[List[str]] = None, prompt: str = "",
                         description: str = "",
                         verification_rules: Optional[Dict[str, Any]] = None
                         ) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise DocumentError("A document type needs a name.")
    slug = _slugify(name)
    if not slug:
        raise DocumentError("That name has no usable characters.")
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise DocumentError("Project not found.")
        if s.query(DocumentType).filter(DocumentType.project_id == project_id,
                                        DocumentType.slug == slug).first():
            raise DocumentError(f"A document type '{slug}' already exists.")
        t = DocumentType(
            id=str(uuid.uuid4()), project_id=project_id, name=name[:120], slug=slug,
            description=description[:1000], sections=sections or [], prompt=prompt[:4000],
            verification_rules=verification_rules or {},
        )
        s.add(t)
        s.commit()
        return _type_dict(t)


def list_document_types(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(DocumentType)
                .filter(DocumentType.project_id == project_id)
                .order_by(DocumentType.name).all())
        return [_type_dict(t) for t in rows]


def delete_document_type(db: DatabaseManager, type_id: str) -> bool:
    with db.get_session() as s:
        t = s.get(DocumentType, type_id)
        if not t:
            return False
        s.delete(t)
        s.commit()
        return True


def verify_against_type(db: DatabaseManager, node_id: str,
                        type_id: str) -> Dict[str, Any]:
    """Deterministic check of a document against its custom type's rules."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        t = s.get(DocumentType, type_id)
        if not node or not t:
            raise DocumentError("Document or type not found.")
        content = node.content or ""
        rules = t.verification_rules or {}
        headings = {sec["heading"].lower() for sec in parse_sections(content) if sec["heading"]}

        failures = []
        if rules.get("require_sections", True):
            for required in (t.sections or []):
                if required.lower() not in headings:
                    failures.append(f"Missing section: {required}")

        min_words = int(rules.get("min_words", 0) or 0)
        words = len(content.split())
        if min_words and words < min_words:
            failures.append(f"Too short: {words} words, needs {min_words}")

        if rules.get("forbid_placeholders", True):
            for marker in ("TODO", "TBD", "Lorem ipsum", "FIXME"):
                if marker.lower() in content.lower():
                    failures.append(f"Contains placeholder text: {marker}")

        return {
            "passed": not failures,
            "failures": failures,
            "word_count": words,
            "type": t.name,
        }
