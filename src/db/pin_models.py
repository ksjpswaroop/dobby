"""
Pins & Favorites (100-Day Roadmap, Day 8).

Deliberately generic rather than one flag-per-entity: a builder pins ideas,
backlog features, and documents from three different tables, and a
`Pin(entity_type, entity_id)` row that points at any of them is simpler than
adding a `pinned`/`order_index` column to each table separately and keeping
three ordering schemes in sync.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from src.db.schema import Base

ENTITY_TYPES = ("idea", "feature", "document")


class Pin(Base):
    __tablename__ = "pins"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "entity_type", "entity_id", name="uq_pin_target"),
        Index("idx_pins_project_order", "project_id", "order_index"),
    )

    def __repr__(self):
        return f"<Pin(entity_type='{self.entity_type}', entity_id='{self.entity_id}')>"
