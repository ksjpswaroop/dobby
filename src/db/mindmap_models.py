"""
Mind-map models.

A map is a tree of nodes (hierarchy via `parent_id`) plus optional cross-branch
edges, with snapshots backing undo/redo. Follows the app's conventions: String
UUID primary keys, a JSON `metadata` column exposed as `extra_metadata`, and
`Base` imported from schema.py so `create_all` picks these tables up.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text

from src.db.schema import Base


class MindMap(Base):
    __tablename__ = "mind_maps"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    session_id = Column(String, index=True)
    title = Column(String, nullable=False)
    root_node_id = Column(String)
    viewport_state = Column(JSON, default=dict)  # {x, y, zoom}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<MindMap(id='{self.id}', title='{self.title}')>"


class MindMapNode(Base):
    __tablename__ = "mind_map_nodes"

    id = Column(String, primary_key=True)
    mind_map_id = Column(String, ForeignKey("mind_maps.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    project_id = Column(String, index=True)
    parent_id = Column(String, ForeignKey("mind_map_nodes.id", ondelete="SET NULL"), index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    node_type = Column(String, nullable=False, default="Idea")
    color = Column(String)
    sort_order = Column(Integer, nullable=False, default=0)
    extra_metadata = Column("metadata", JSON, default=dict)  # position, priority, status
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_mmn_map_parent", "mind_map_id", "parent_id"),)

    def __repr__(self):
        return f"<MindMapNode(id='{self.id}', title='{self.title}')>"


class MindMapEdge(Base):
    """A cross-branch link, distinct from the parent/child hierarchy."""

    __tablename__ = "mind_map_edges"

    id = Column(String, primary_key=True)
    mind_map_id = Column(String, ForeignKey("mind_maps.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    source_node_id = Column(String, ForeignKey("mind_map_nodes.id", ondelete="CASCADE"),
                            nullable=False)
    target_node_id = Column(String, ForeignKey("mind_map_nodes.id", ondelete="CASCADE"),
                            nullable=False)
    relation_type = Column(String, default="related")
    created_at = Column(DateTime, default=datetime.utcnow)


class MindMapSnapshot(Base):
    """A serialized map state, used for undo/redo and pre-AI-change safety."""

    __tablename__ = "mind_map_snapshots"

    id = Column(String, primary_key=True)
    mind_map_id = Column(String, ForeignKey("mind_maps.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    snapshot_json = Column(Text, nullable=False)
    operation_label = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_mms_map_time", "mind_map_id", "created_at"),)
