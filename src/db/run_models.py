"""
Run & event models — the storage behind Logs & Traces.

A **Run** is one unit of observable work (a YOLO generation, a wizard step, a
bulk batch). A **RunEvent** is a timestamped step inside it. Together they turn
the generation pipelines from a black box into an inspectable timeline.

Kept in a separate module (imported by `schema.py`) so `schema.py` doesn't grow
monolithic; `Base.metadata.create_all` still picks these tables up.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text

from src.db.schema import Base


class Run(Base):
    """One observable unit of work (yolo | wizard_step | bulk | verify)."""

    __tablename__ = "runs"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True)
    kind = Column(String, nullable=False, index=True)  # yolo | wizard | bulk | verify
    label = Column(String, nullable=False)  # human title, e.g. the feature name
    status = Column(String, nullable=False, default="running")  # running|ok|failed|cancelled
    model = Column(String)
    node_id = Column(String)  # the feature node produced, when applicable
    error = Column(Text)
    total_steps = Column(Integer, default=0)
    completed_steps = Column(Integer, default=0)
    score = Column(Float)  # final verification score, when applicable
    duration_ms = Column(Integer)
    extra_metadata = Column("metadata", JSON, default=dict)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)

    __table_args__ = (Index("idx_runs_project_started", "project_id", "started_at"),)

    def __repr__(self):
        return f"<Run(id='{self.id}', kind='{self.kind}', status='{self.status}')>"


class RunEvent(Base):
    """A single timestamped step inside a run."""

    __tablename__ = "run_events"

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False, default=0)
    level = Column(String, nullable=False, default="info")  # info | warn | error
    event = Column(String, nullable=False)  # machine name, e.g. "step.start"
    message = Column(Text, nullable=False, default="")  # human line
    step = Column(String)  # e.g. "pseudocode"
    duration_ms = Column(Integer)
    tokens = Column(Integer)
    score = Column(Float)
    extra_metadata = Column("metadata", JSON, default=dict)
    ts = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_run_events_run_seq", "run_id", "seq"),)

    def __repr__(self):
        return f"<RunEvent(run='{self.run_id}', seq={self.seq}, event='{self.event}')>"
