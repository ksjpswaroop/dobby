"""
Quality & trust (100-Day Roadmap, Phase 9).

`TrashItem` is the recoverable-delete store (D90). Deleting anything in Dobby
serialises the row (and its dependents) into JSON here rather than dropping
it, so restore is a real operation and not a promise. Items are only actually
gone when the user empties the trash — which is the one destructive action
the app never takes on its own.

`BatchJob` (D86) exists so a bulk operation survives a page refresh. Running
forty verifications inside a request would tie the outcome to a browser tab
staying open; instead the job is a row, each item's outcome is recorded on
it, and the UI polls.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text

from src.db.schema import Base

TRASH_KINDS = ("idea", "feature", "document", "comment", "sprint", "objective")
BATCH_OPERATIONS = ("verify", "tag", "export", "set_status", "move_column", "delete")
BATCH_STATES = ("queued", "running", "done", "cancelled")


class TrashItem(Base):
    """A soft-deleted record, restorable until the trash is emptied."""

    __tablename__ = "trash_items"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    kind = Column(String, nullable=False, index=True)
    original_id = Column(String, nullable=False, index=True)
    label = Column(String, default="")
    # The full row(s) as JSON. Dependents (a document's versions, a comment's
    # replies) travel with the parent so a restore brings back the whole thing.
    payload = Column(JSON, default=dict)
    deleted_at = Column(DateTime, default=datetime.utcnow, index=True)
    restored_at = Column(DateTime)

    __table_args__ = (Index("idx_trash_project_deleted", "project_id", "deleted_at"),)


class BatchJob(Base):
    """A bulk operation over many targets, durable across refreshes."""

    __tablename__ = "batch_jobs"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    operation = Column(String, nullable=False)
    state = Column(String, default="queued", index=True)
    # [{target_id, title, status, detail}] — per-item so a partial failure is
    # visible rather than collapsing the whole job into "failed".
    items = Column(JSON, default=list)
    params = Column(JSON, default=dict)
    total = Column(Integer, default=0)
    completed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)


class ConsistencyIssue(Base):
    """One finding from the project-wide consistency pass (D84)."""

    __tablename__ = "consistency_issues"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    kind = Column(String, nullable=False, index=True)
    severity = Column(String, default="warning")  # info | warning | error
    title = Column(String, nullable=False)
    detail = Column(Text, default="")
    node_ids = Column(JSON, default=list)
    resolved = Column(Integer, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
