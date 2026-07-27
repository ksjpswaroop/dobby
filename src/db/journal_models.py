"""
Journal (Work Graph, step 5).

Deliberately *not* a second capture inbox. Ideas already own frictionless
capture; a competing surface would only split people's thoughts across two
places. A journal entry is a dated reflection, and one entry per date per
kind — a journal that accumulates six half-written entries for the same
evening is one nobody reads back.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)

from src.db.schema import Base

ENTRY_KINDS = ("reflection", "weekly", "retro")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    # ISO local date. A string, not a DateTime: "which day was this" is a
    # calendar question, and storing a timestamp invites timezone drift.
    entry_date = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, default="reflection")
    title = Column(String, default="")
    body = Column(Text, nullable=False)
    highlights = Column(JSON, default=list)
    # Whether this is still an untouched auto-draft. Cleared the moment a
    # human edits it, so "you have not written today" stays truthful.
    auto_drafted = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "entry_date", "kind", name="uq_journal_day"),
        Index("idx_journal_project_date", "project_id", "entry_date"),
    )
