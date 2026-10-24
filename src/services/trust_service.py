"""
Trash, backup, consistency, and batch operations (Phase 9: D84, D86, D87, D90).

The through-line is **nothing is destroyed without a way back**. Deletes go to
trash rather than dropping rows; a project export is a complete, versioned
archive that can rebuild the project elsewhere; batch operations record a
per-item outcome so a partial failure is visible rather than collapsing into
"failed".

Import is deliberately additive-with-new-ids by default. Restoring an archive
over a live project by reusing its primary keys would silently overwrite work
that happens to share an id — so the safe mode is the default and overwriting
is an explicit choice.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.document_models import Comment, DocumentMeta, NodeVersion, NodeTag, Tag
from src.db.idea_models import Idea
from src.db.planning_models import Blocker, PlanningMeta
from src.db.schema import DatabaseManager, Edge, FeatureBacklog, Node, Project
from src.db.trust_models import (
    BATCH_OPERATIONS, BATCH_STATES, TRASH_KINDS, BatchJob, ConsistencyIssue, TrashItem,
)

logger = structlog.get_logger()

ARCHIVE_VERSION = 1


class TrustError(Exception):
    pass


# ---------------------------------------------------------------------------
# Trash (D90)
# ---------------------------------------------------------------------------
def _column_attrs(model_or_obj):
    """Python attribute names, not table column names.

    These differ where a column is remapped — `Node.extra_metadata` is stored
    in a DB column literally called `metadata`, and reading that name off the
    instance returns SQLAlchemy's own `MetaData` object rather than the JSON
    the caller wanted.
    """
    from sqlalchemy import inspect as sa_inspect

    return list(sa_inspect(model_or_obj).mapper.column_attrs)


def _serialise(obj) -> Dict[str, Any]:
    out = {}
    for attr in _column_attrs(obj):
        value = getattr(obj, attr.key, None)
        if isinstance(value, datetime):
            value = value.isoformat()
        out[attr.key] = value
    return out


def _revive(model, data: Dict[str, Any]):
    kwargs = {}
    for attr in _column_attrs(model):
        if attr.key not in data:
            continue
        value = data[attr.key]
        column = attr.columns[0]
        if value is not None and str(column.type).upper().startswith("DATETIME"):
            try:
                value = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                value = None
        kwargs[attr.key] = value
    return model(**kwargs)


def trash_idea(db: DatabaseManager, idea_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        idea = s.get(Idea, idea_id)
        if not idea:
            raise TrustError("Idea not found.")
        item = TrashItem(
            id=str(uuid.uuid4()), project_id=idea.project_id, kind="idea",
            original_id=idea.id, label=(idea.text or "")[:120],
            payload={"idea": _serialise(idea)},
        )
        s.add(item)
        s.delete(idea)
        s.commit()
        return _trash_dict(item)


def trash_document(db: DatabaseManager, node_id: str) -> Dict[str, Any]:
    """Soft-delete a document *with* its versions, comments, and tag links."""
    with db.get_session() as s:
        node = s.get(Node, node_id)
        if not node:
            raise TrustError("Document not found.")

        versions = s.query(NodeVersion).filter(NodeVersion.node_id == node_id).all()
        comments = s.query(Comment).filter(Comment.node_id == node_id).all()
        links = s.query(NodeTag).filter(NodeTag.node_id == node_id).all()
        meta = s.get(DocumentMeta, node_id)

        item = TrashItem(
            id=str(uuid.uuid4()), project_id=node.project_id, kind="document",
            original_id=node.id, label=(node.title or "")[:120],
            payload={
                "node": _serialise(node),
                "versions": [_serialise(v) for v in versions],
                "comments": [_serialise(c) for c in comments],
                "tag_links": [_serialise(l) for l in links],
                "meta": _serialise(meta) if meta else None,
            },
        )
        s.add(item)
        # Delete dependents first; the flush ordering matters for the same
        # reason it did for comment replies.
        for row in [*versions, *comments, *links] + ([meta] if meta else []):
            s.delete(row)
        s.flush()
        s.delete(node)
        s.commit()
        return _trash_dict(item)


def trash_feature(db: DatabaseManager, feature_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        f = s.get(FeatureBacklog, feature_id)
        if not f:
            raise TrustError("Feature not found.")
        meta = s.get(PlanningMeta, feature_id)
        blockers = (s.query(Blocker)
                    .filter((Blocker.feature_id == feature_id)
                            | (Blocker.blocked_by_id == feature_id)).all())
        item = TrashItem(
            id=str(uuid.uuid4()), project_id=f.project_id, kind="feature",
            original_id=f.id, label=(f.title or "")[:120],
            payload={
                "feature": _serialise(f),
                "meta": _serialise(meta) if meta else None,
                "blockers": [_serialise(b) for b in blockers],
            },
        )
        s.add(item)
        for b in blockers:
            s.delete(b)
        if meta:
            s.delete(meta)
        s.flush()
        s.delete(f)
        s.commit()
        return _trash_dict(item)


def _trash_dict(item: TrashItem) -> Dict[str, Any]:
    return {
        "id": item.id, "kind": item.kind, "original_id": item.original_id,
        "label": item.label, "project_id": item.project_id,
        "deleted_at": item.deleted_at.isoformat() if item.deleted_at else None,
        "restored": item.restored_at is not None,
    }


def list_trash(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(TrashItem)
                .filter(TrashItem.project_id == project_id,
                        TrashItem.restored_at.is_(None))
                .order_by(TrashItem.deleted_at.desc()).all())
        return [_trash_dict(t) for t in rows]


def restore(db: DatabaseManager, trash_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        item = s.get(TrashItem, trash_id)
        if not item:
            raise TrustError("Trash item not found.")
        if item.restored_at:
            raise TrustError("That item has already been restored.")

        payload = item.payload or {}
        if item.kind == "idea":
            s.add(_revive(Idea, payload["idea"]))
        elif item.kind == "document":
            s.add(_revive(Node, payload["node"]))
            s.flush()
            for v in payload.get("versions", []):
                s.add(_revive(NodeVersion, v))
            for c in payload.get("comments", []):
                s.add(_revive(Comment, c))
            for l in payload.get("tag_links", []):
                s.add(_revive(NodeTag, l))
            if payload.get("meta"):
                s.add(_revive(DocumentMeta, payload["meta"]))
        elif item.kind == "feature":
            s.add(_revive(FeatureBacklog, payload["feature"]))
            s.flush()
            if payload.get("meta"):
                s.add(_revive(PlanningMeta, payload["meta"]))
            for b in payload.get("blockers", []):
                s.add(_revive(Blocker, b))
        else:
            raise TrustError(f"Cannot restore a {item.kind} yet.")

        item.restored_at = datetime.utcnow()
        s.commit()
        return {"restored": item.kind, "original_id": item.original_id}


def empty_trash(db: DatabaseManager, project_id: str) -> int:
    """The one genuinely destructive action — only ever user-initiated."""
    with db.get_session() as s:
        rows = (s.query(TrashItem)
                .filter(TrashItem.project_id == project_id,
                        TrashItem.restored_at.is_(None)).all())
        n = len(rows)
        for r in rows:
            s.delete(r)
        s.commit()
        return n


# ---------------------------------------------------------------------------
# Export / import (D87)
# ---------------------------------------------------------------------------
def export_project(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """A complete, versioned, portable archive of a project."""
    with db.get_session() as s:
        project = s.get(Project, project_id)
        if not project:
            raise TrustError("Project not found.")

        def rows(model, field="project_id"):
            return [_serialise(r) for r in
                    s.query(model).filter(getattr(model, field) == project_id).all()]

        nodes = s.query(Node).filter(Node.project_id == project_id).all()
        node_ids = [n.id for n in nodes]

        versions, comments, tag_links, metas = [], [], [], []
        if node_ids:
            versions = [_serialise(v) for v in s.query(NodeVersion)
                        .filter(NodeVersion.node_id.in_(node_ids)).all()]
            comments = [_serialise(c) for c in s.query(Comment)
                        .filter(Comment.node_id.in_(node_ids)).all()]
            tag_links = [_serialise(l) for l in s.query(NodeTag)
                         .filter(NodeTag.node_id.in_(node_ids)).all()]
            metas = [_serialise(m) for m in s.query(DocumentMeta)
                     .filter(DocumentMeta.node_id.in_(node_ids)).all()]

        archive = {
            "archive_version": ARCHIVE_VERSION,
            "exported_at": datetime.utcnow().isoformat(),
            "project": _serialise(project),
            "nodes": [_serialise(n) for n in nodes],
            "node_versions": versions,
            "comments": comments,
            "document_meta": metas,
            "tags": rows(Tag),
            "tag_links": tag_links,
            "features": rows(FeatureBacklog),
            "planning_meta": rows(PlanningMeta),
            "blockers": rows(Blocker),
            "ideas": rows(Idea),
            "edges": [_serialise(e) for e in
                      s.query(Edge).filter(Edge.project_id == project_id).all()],
        }
        archive["counts"] = {k: len(v) for k, v in archive.items() if isinstance(v, list)}
        return archive


def import_project(db: DatabaseManager, archive: Dict[str, Any],
                   new_project_name: str = "") -> Dict[str, Any]:
    """Import an archive as a *new* project with fresh ids.

    Reusing the archive's primary keys would silently overwrite anything on
    this machine that happens to share an id, so a new project is the only
    mode offered. Nothing existing is ever touched.
    """
    if not isinstance(archive, dict):
        raise TrustError("That is not a Dobby archive.")
    version = archive.get("archive_version")
    if version != ARCHIVE_VERSION:
        raise TrustError(
            f"Archive version {version} is not supported (expected {ARCHIVE_VERSION})."
        )
    if "project" not in archive:
        raise TrustError("Archive is missing its project record.")

    new_project_id = str(uuid.uuid4())
    node_map: Dict[str, str] = {}
    feature_map: Dict[str, str] = {}
    tag_map: Dict[str, str] = {}

    with db.get_session() as s:
        src = archive["project"]
        s.add(Project(
            id=new_project_id,
            name=(new_project_name or f"{src.get('name', 'Imported')} (imported)")[:200],
            idea=src.get("idea"), description=src.get("description"),
            status="active",
        ))
        s.flush()

        for n in archive.get("nodes", []):
            new_id = str(uuid.uuid4())
            node_map[n["id"]] = new_id
            data = dict(n, id=new_id, project_id=new_project_id)
            data["parent_id"] = None  # remapped below once every node exists
            s.add(_revive(Node, data))
        s.flush()

        # Second pass for parents, now that every node has an id.
        for n in archive.get("nodes", []):
            if n.get("parent_id") and n["parent_id"] in node_map:
                node = s.get(Node, node_map[n["id"]])
                node.parent_id = node_map[n["parent_id"]]

        for f in archive.get("features", []):
            new_id = str(uuid.uuid4())
            feature_map[f["id"]] = new_id
            data = dict(f, id=new_id, project_id=new_project_id)
            data["node_id"] = node_map.get(f.get("node_id")) if f.get("node_id") else None
            s.add(_revive(FeatureBacklog, data))

        for t in archive.get("tags", []):
            new_id = str(uuid.uuid4())
            tag_map[t["id"]] = new_id
            s.add(_revive(Tag, dict(t, id=new_id, project_id=new_project_id)))

        for i in archive.get("ideas", []):
            s.add(_revive(Idea, dict(i, id=str(uuid.uuid4()),
                                     project_id=new_project_id,
                                     promoted_feature_id=None, promoted_brief_id=None)))
        s.flush()

        for v in archive.get("node_versions", []):
            if v.get("node_id") in node_map:
                s.add(_revive(NodeVersion, dict(v, id=str(uuid.uuid4()),
                                                node_id=node_map[v["node_id"]],
                                                project_id=new_project_id)))
        for c in archive.get("comments", []):
            if c.get("node_id") in node_map:
                s.add(_revive(Comment, dict(c, id=str(uuid.uuid4()),
                                            node_id=node_map[c["node_id"]],
                                            project_id=new_project_id,
                                            parent_id=None)))
        for m in archive.get("document_meta", []):
            if m.get("node_id") in node_map:
                s.add(_revive(DocumentMeta, dict(m, node_id=node_map[m["node_id"]],
                                                 project_id=new_project_id)))
        for l in archive.get("tag_links", []):
            if l.get("node_id") in node_map and l.get("tag_id") in tag_map:
                s.add(_revive(NodeTag, dict(l, id=str(uuid.uuid4()),
                                            node_id=node_map[l["node_id"]],
                                            tag_id=tag_map[l["tag_id"]])))
        for pm in archive.get("planning_meta", []):
            if pm.get("feature_id") in feature_map:
                s.add(_revive(PlanningMeta, dict(
                    pm, feature_id=feature_map[pm["feature_id"]],
                    project_id=new_project_id, sprint_id=None, milestone_id=None)))
        for b in archive.get("blockers", []):
            if b.get("feature_id") in feature_map and b.get("blocked_by_id") in feature_map:
                s.add(_revive(Blocker, dict(
                    b, id=str(uuid.uuid4()), project_id=new_project_id,
                    feature_id=feature_map[b["feature_id"]],
                    blocked_by_id=feature_map[b["blocked_by_id"]])))
        for e in archive.get("edges", []):
            if e.get("source_node_id") in node_map and e.get("target_node_id") in node_map:
                s.add(_revive(Edge, dict(
                    e, id=str(uuid.uuid4()), project_id=new_project_id,
                    source_node_id=node_map[e["source_node_id"]],
                    target_node_id=node_map[e["target_node_id"]])))

        s.commit()

    return {
        "project_id": new_project_id,
        "nodes": len(node_map),
        "features": len(feature_map),
        "tags": len(tag_map),
    }


# ---------------------------------------------------------------------------
# Consistency checker (D84)
# ---------------------------------------------------------------------------
PLACEHOLDERS = ("TODO", "TBD", "FIXME", "Lorem ipsum", "XXX")


def check_consistency(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """A deterministic project-wide pass. No model involved, so it is fast,
    repeatable, and its findings are always literally true."""
    issues: List[Dict[str, Any]] = []

    def add(kind: str, severity: str, title: str, detail: str = "",
            node_ids: Optional[List[str]] = None):
        issues.append({"kind": kind, "severity": severity, "title": title,
                       "detail": detail, "node_ids": node_ids or []})

    with db.get_session() as s:
        nodes = s.query(Node).filter(Node.project_id == project_id).all()
        features = (s.query(FeatureBacklog)
                    .filter(FeatureBacklog.project_id == project_id).all())

        for n in nodes:
            content = n.content or ""
            for marker in PLACEHOLDERS:
                if marker.lower() in content.lower():
                    add("placeholder", "warning",
                        f"“{n.title}” still contains {marker}",
                        "Placeholder text usually means the section was never finished.",
                        [n.id])
                    break
            if len(content.split()) < 30:
                add("thin_document", "warning", f"“{n.title}” is very short",
                    f"{len(content.split())} words — likely a stub.", [n.id])

        # Wiki links that point nowhere.
        from src.services.document_service import extract_wikilinks

        titles = {(n.title or "").lower() for n in nodes}
        for n in nodes:
            for link in extract_wikilinks(n.content or ""):
                if link.lower() not in titles:
                    add("broken_link", "error",
                        f"“{n.title}” links to a document that does not exist",
                        f"[[{link}]] does not resolve.", [n.id])

        # Features with no document written for them.
        node_titles_blob = " ".join((n.title or "") + " " + (n.content or "")
                                    for n in nodes).lower()
        for f in features:
            if f.status in ("completed",) and f.title.lower() not in node_titles_blob:
                add("undocumented_feature", "warning",
                    f"“{f.title}” is marked complete but no document mentions it",
                    "Completed work with no written record drifts out of the project.")

        # Duplicate document titles make wiki links ambiguous.
        seen: Dict[str, str] = {}
        for n in nodes:
            key = (n.title or "").lower()
            if key and key in seen:
                add("duplicate_title", "warning",
                    f"Two documents are both called “{n.title}”",
                    "Wiki links to this title cannot resolve unambiguously.",
                    [seen[key], n.id])
            elif key:
                seen[key] = n.id

        # Persist, replacing the previous unresolved run so the list reflects
        # the current state rather than accumulating history.
        for old in (s.query(ConsistencyIssue)
                    .filter(ConsistencyIssue.project_id == project_id,
                            ConsistencyIssue.resolved == 0).all()):
            s.delete(old)
        s.flush()
        for i in issues:
            s.add(ConsistencyIssue(
                id=str(uuid.uuid4()), project_id=project_id, kind=i["kind"],
                severity=i["severity"], title=i["title"], detail=i["detail"],
                node_ids=i["node_ids"]))
        s.commit()

    by_severity = {sev: sum(1 for i in issues if i["severity"] == sev)
                   for sev in ("error", "warning", "info")}
    return {"issues": issues, "count": len(issues), "by_severity": by_severity,
            "clean": not issues}


def list_issues(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(ConsistencyIssue)
                .filter(ConsistencyIssue.project_id == project_id,
                        ConsistencyIssue.resolved == 0)
                .order_by(ConsistencyIssue.severity).all())
        return [{"id": r.id, "kind": r.kind, "severity": r.severity,
                 "title": r.title, "detail": r.detail, "node_ids": r.node_ids or []}
                for r in rows]


# ---------------------------------------------------------------------------
# Batch operations (D86)
# ---------------------------------------------------------------------------
def run_batch(db: DatabaseManager, project_id: str, operation: str,
              target_ids: List[str], params: Optional[Dict[str, Any]] = None
              ) -> Dict[str, Any]:
    """Run one operation over many targets, recording a per-item outcome."""
    if operation not in BATCH_OPERATIONS:
        raise TrustError(f"Unknown operation. One of: {', '.join(BATCH_OPERATIONS)}")
    if not target_ids:
        raise TrustError("Select something first.")

    params = params or {}
    job_id = str(uuid.uuid4())
    items: List[Dict[str, Any]] = []

    from src.services import document_service as docs
    from src.services import planning_service as planning

    for target in target_ids:
        entry = {"target_id": target, "status": "ok", "detail": ""}
        try:
            if operation == "tag":
                name = params.get("name")
                if not name:
                    raise TrustError("A tag name is required.")
                docs.add_tag(db, project_id, target, name)
            elif operation == "set_status":
                docs.set_status(db, target, params.get("status", "in_review"))
            elif operation == "move_column":
                planning.move_card(db, target, params.get("column", "todo"))
            elif operation == "delete":
                kind = params.get("kind", "document")
                if kind == "document":
                    trash_document(db, target)
                elif kind == "feature":
                    trash_feature(db, target)
                elif kind == "idea":
                    trash_idea(db, target)
                else:
                    raise TrustError(f"Cannot batch-delete {kind}.")
            elif operation == "export":
                doc = docs.get_document(db, target)
                if not doc:
                    raise TrustError("Document not found.")
                entry["detail"] = f"{doc['word_count']} words"
            elif operation == "verify":
                type_id = params.get("type_id")
                if type_id:
                    out = docs.verify_against_type(db, target, type_id)
                    entry["status"] = "ok" if out["passed"] else "failed"
                    entry["detail"] = "; ".join(out["failures"][:3])
                else:
                    doc = docs.get_document(db, target)
                    if not doc:
                        raise TrustError("Document not found.")
                    thin = doc["word_count"] < 30
                    entry["status"] = "failed" if thin else "ok"
                    entry["detail"] = "too short" if thin else "looks complete"
        except Exception as e:
            entry["status"] = "failed"
            entry["detail"] = str(e)[:300]
        items.append(entry)

    failed = sum(1 for i in items if i["status"] == "failed")
    with db.get_session() as s:
        s.add(BatchJob(
            id=job_id, project_id=project_id, operation=operation, state="done",
            items=items, params=params, total=len(items),
            completed=len(items) - failed, failed=failed,
            finished_at=datetime.utcnow(),
        ))
        s.commit()

    return {"job_id": job_id, "operation": operation, "total": len(items),
            "completed": len(items) - failed, "failed": failed, "items": items}


def list_jobs(db: DatabaseManager, project_id: str,
              limit: int = 20) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(BatchJob).filter(BatchJob.project_id == project_id)
                .order_by(BatchJob.created_at.desc()).limit(limit).all())
        return [{"id": j.id, "operation": j.operation, "state": j.state,
                 "total": j.total, "completed": j.completed, "failed": j.failed,
                 "created_at": j.created_at.isoformat() if j.created_at else None}
                for j in rows]
