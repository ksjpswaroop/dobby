"""
Living documents (100-Day Roadmap, Phase 2: Days 11-20).

These five tables turn a generated `Node` from a read-only artifact into
something a builder edits every day.

`NodeVersion` is the load-bearing one. Every content change — a manual save,
a section regeneration, an inline refine, a restore — writes an immutable
snapshot before mutating the node. That is what makes aggressive editing
safe, and it is why regeneration and refine can be offered as one-click
actions at all: nothing they do is unrecoverable.

`Comment` anchors to character offsets rather than to a rendered selection,
because offsets are the only anchor that survives a round-trip through
storage. Offsets do drift when text above them changes; `anchor_text` is
kept alongside so a drifted comment can be re-found by content instead of
silently pointing at the wrong sentence.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)

from src.db.schema import Base

# Document lifecycle. Deliberately shorter than the node `status` field
# (draft/in_progress/verified/finalized), which tracks *generation* state;
# this tracks *editorial* state, and the two move independently.
DOC_STATUSES = ("draft", "in_review", "approved")

# Which transitions are allowed. Approved work can be reopened to review but
# never jumps straight back to draft — that would quietly discard the fact
# that it was reviewed at all.
STATUS_TRANSITIONS = {
    "draft": ("in_review",),
    "in_review": ("draft", "approved"),
    "approved": ("in_review",),
}

VERSION_REASONS = ("edit", "regenerate_section", "refine", "restore", "import")


class NodeVersion(Base):
    """An immutable snapshot of a node's content, written before each change."""

    __tablename__ = "node_versions"

    id = Column(String, primary_key=True)
    node_id = Column(String, ForeignKey("nodes.id"), index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    version = Column(Integer, nullable=False)
    title = Column(String)
    content = Column(Text)
    # Why this snapshot exists, so the history panel can say "AI refine"
    # rather than showing the user an undifferentiated list of saves.
    reason = Column(String, nullable=False, default="edit")
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("node_id", "version", name="uq_node_version"),
        Index("idx_versions_node_created", "node_id", "created_at"),
    )

    def __repr__(self):
        return f"<NodeVersion(node='{self.node_id}', v={self.version}, reason='{self.reason}')>"


class DocumentMeta(Base):
    """Editorial state for a node: workflow status and its history.

    Separate from `Node` so the generation pipeline's columns stay untouched;
    a node with no row here is simply a draft.
    """

    __tablename__ = "document_meta"

    node_id = Column(String, ForeignKey("nodes.id"), primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    status = Column(String, nullable=False, default="draft", index=True)
    status_changed_at = Column(DateTime, default=datetime.utcnow)
    # Append-only [{from, to, at}] so "how did this doc mature" is answerable.
    status_history = Column(JSON, default=list)
    dirty = Column(Integer, default=0)  # edited since last verification
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<DocumentMeta(node='{self.node_id}', status='{self.status}')>"


class Comment(Base):
    """A threaded note anchored to a character range in a node's content."""

    __tablename__ = "comments"

    id = Column(String, primary_key=True)
    node_id = Column(String, ForeignKey("nodes.id"), index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    parent_id = Column(String, ForeignKey("comments.id"), index=True)  # reply threading
    body = Column(Text, nullable=False)
    start_offset = Column(Integer)
    end_offset = Column(Integer)
    # The text the comment was written against, so a drifted anchor can be
    # relocated by search instead of pointing at the wrong sentence.
    anchor_text = Column(Text, default="")
    resolved = Column(Integer, default=0, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_comments_node_resolved", "node_id", "resolved"),)

    def __repr__(self):
        return f"<Comment(node='{self.node_id}', resolved={self.resolved})>"


class Tag(Base):
    """A free-form label, scoped to a project."""

    __tablename__ = "tags"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    color = Column(String, default="neutral")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_tag_name"),)

    def __repr__(self):
        return f"<Tag(name='{self.name}')>"


class NodeTag(Base):
    """Join row attaching a tag to a node."""

    __tablename__ = "node_tags"

    id = Column(String, primary_key=True)
    node_id = Column(String, ForeignKey("nodes.id"), index=True, nullable=False)
    tag_id = Column(String, ForeignKey("tags.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("node_id", "tag_id", name="uq_node_tag"),)


class DocumentType(Base):
    """A user-defined document type beyond the built-in seven (D20)."""

    __tablename__ = "document_types"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    description = Column(Text, default="")
    # Ordered section headings the generator must produce and the verifier checks.
    sections = Column(JSON, default=list)
    prompt = Column(Text, default="")
    # {min_words, require_sections, forbid_placeholders}
    verification_rules = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_doctype_slug"),)

    def __repr__(self):
        return f"<DocumentType(slug='{self.slug}')>"
