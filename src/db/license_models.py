"""
License model — the authority's own record of what it has issued.

Kept here rather than inline in `src/licensing/authority.py`, matching every
other feature's convention (models under `src/db/`, service logic
elsewhere) — imported by `schema.py` so `Base.metadata.create_all` picks up
its table, same as `automation_models`, `inbox_models`, etc.

This table is conceptually server-side. It living in the same SQLite file as
everything else is a development convenience, not the target architecture —
see `src/licensing/__init__.py`.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from src.db.schema import Base


class License(Base):
    """One issued license."""

    __tablename__ = "licenses"

    id = Column(String, primary_key=True)
    tier = Column(String, nullable=False)
    seats = Column(Integer, default=1)
    email = Column(String, default="")
    issued_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updates_until = Column(DateTime)  # NULL = perpetual updates (support only)
    revoked_at = Column(DateTime)

    def __repr__(self):
        return f"<License(id='{self.id}', tier='{self.tier}')>"
