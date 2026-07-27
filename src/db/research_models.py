"""
Research models — storage for the Research stage that runs *before* Create.

A **ResearchBrief** is one investigation of a topic. It fans out into
**ResearchTracks** (product, market, competition, business, technical), each of
which accumulates **ResearchLearnings** distilled from **ResearchSources**.

Why tracks rather than one report: a founder does not need "a research report",
they need to know what to build, who wants it, who else is doing it, and how it
makes money. Those are different questions with different evidence, and keeping
them separate is what lets a finding become a backlog item later.

Kept separate from `schema.py` so it doesn't grow monolithic;
`Base.metadata.create_all` still picks these tables up.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
)

from src.db.schema import Base

# The five questions a product research pass has to answer. Order matters —
# this is the sequence they are presented and generated in.
TRACK_KINDS = ("product", "market", "competition", "business", "technical")

TRACK_LABELS = {
    "product": "Product",
    "market": "Market",
    "competition": "Competition",
    "business": "Business model",
    "technical": "Technical feasibility",
}


class ResearchBrief(Base):
    """One research investigation of a topic, spanning several tracks."""

    __tablename__ = "research_briefs"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True, nullable=False)
    topic = Column(String, nullable=False)
    # Free-text steer from the user ("focus on the EU market", "we're B2B").
    context = Column(Text, default="")
    status = Column(String, nullable=False, default="pending", index=True)
    # pending | planning | researching | synthesizing | complete | failed
    plan = Column(Text, default="")
    summary = Column(Text, default="")
    search_provider = Column(String, default="none")
    model = Column(String)
    error = Column(Text)
    run_id = Column(String, index=True)  # links to the Logs & Traces timeline
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("idx_briefs_project_created", "project_id", "created_at"),)

    def __repr__(self):
        return f"<ResearchBrief(id='{self.id}', topic='{self.topic[:30]}')>"


class ResearchTrack(Base):
    """One angle of investigation within a brief."""

    __tablename__ = "research_tracks"

    id = Column(String, primary_key=True)
    brief_id = Column(String, ForeignKey("research_briefs.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)  # one of TRACK_KINDS
    status = Column(String, nullable=False, default="pending")
    # The synthesized markdown for this track.
    content = Column(Text, default="")
    # Model's own confidence that the evidence supports the conclusions (0-100).
    confidence = Column(Float)
    sort_order = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ResearchTrack(kind='{self.kind}', status='{self.status}')>"


class ResearchSource(Base):
    """Where a learning came from.

    `kind` distinguishes real retrieved documents from the model's own prior
    knowledge — without that, a report grounded in nothing looks identical to
    one grounded in sources, which is the single most misleading thing a
    research tool can do.
    """

    __tablename__ = "research_sources"

    id = Column(String, primary_key=True)
    brief_id = Column(String, ForeignKey("research_briefs.id"), index=True, nullable=False)
    track_kind = Column(String, index=True)
    kind = Column(String, nullable=False, default="model")  # model | web | project
    title = Column(String, default="")
    url = Column(String, default="")
    snippet = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ResearchLearning(Base):
    """A single distilled finding, the unit that can become a backlog item."""

    __tablename__ = "research_learnings"

    id = Column(String, primary_key=True)
    brief_id = Column(String, ForeignKey("research_briefs.id"), index=True, nullable=False)
    track_kind = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=False)
    # Set when the user promotes this finding into the feature backlog, so the
    # Research → Create hand-off is visible from both ends.
    promoted_feature_id = Column(String, index=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_learnings_brief_track", "brief_id", "track_kind"),)
