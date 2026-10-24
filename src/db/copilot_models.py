"""
AI Copilot subsystem (100-Day Roadmap, Phase 3: Days 21-30).

Four tables behind nine roadmap features:

`ModelCall` is the telemetry spine (D30). Every model invocation writes one
row — task type, model, tokens, latency. That single log is what makes the
usage dashboard, per-task routing decisions, and "which model is actually
faster for chat" answerable with data instead of guesses.

`PromptTemplate` (D27) stores both Dobby's built-in prompts and user forks of
them. A fork records `forked_from` so a user can see what they changed and
reset to the original.

`ChatThread`/`ChatMessage` (D21, D26) persist copilot conversations. A thread
with `project_id = None` is the cross-project global copilot; the same tables
serve both because the only real difference is retrieval scope.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)

from src.db.schema import Base

# Task types that can be routed to different models (D28) and that telemetry
# buckets by (D30).
TASK_TYPES = (
    "generate", "chat", "summarize", "prioritize", "refine",
    "regenerate_section", "research", "embed", "other",
)


class ModelCall(Base):
    """One model invocation, logged for the usage dashboard."""

    __tablename__ = "model_calls"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True)
    task_type = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False, index=True)
    provider = Column(String, default="")
    prompt_chars = Column(Integer, default=0)
    output_chars = Column(Integer, default=0)
    # Token counts are estimated for local models, which do not report usage.
    # Kept separate from chars so a provider that *does* report real numbers
    # can overwrite them without the estimate silently masquerading as truth.
    prompt_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    tokens_estimated = Column(Integer, default=1)
    latency_ms = Column(Integer, default=0)
    ok = Column(Integer, default=1)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_calls_task_created", "task_type", "created_at"),
        Index("idx_calls_model_created", "model", "created_at"),
    )

    def __repr__(self):
        return f"<ModelCall(task='{self.task_type}', model='{self.model}')>"


class PromptTemplate(Base):
    """A reusable prompt — built-in, or a user's fork of one (D27)."""

    __tablename__ = "prompt_templates"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True)  # None = available to every project
    slug = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    body = Column(Text, nullable=False)
    # Declared {{variables}} so the UI can render inputs and validate before running.
    variables = Column(JSON, default=list)
    task_type = Column(String, default="other")
    builtin = Column(Integer, default=0)
    forked_from = Column(String)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_prompt_slug"),
    )

    def __repr__(self):
        return f"<PromptTemplate(slug='{self.slug}', builtin={self.builtin})>"


class ChatThread(Base):
    """A copilot conversation. `project_id = None` means the global copilot."""

    __tablename__ = "chat_threads"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True)
    title = Column(String, default="New chat")
    scope = Column(String, default="project")  # project | global
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ChatThread(id='{self.id}', scope='{self.scope}')>"


class ChatMessage(Base):
    """One turn. Assistant turns carry the citations they were grounded on."""

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True)
    thread_id = Column(String, ForeignKey("chat_threads.id"), index=True, nullable=False)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    # [{node_id, title, project_id, score}] — what the answer was built from,
    # so a claim can always be traced back to a document the user owns.
    citations = Column(JSON, default=list)
    model = Column(String, default="")
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_messages_thread_created", "thread_id", "created_at"),)

    def __repr__(self):
        return f"<ChatMessage(role='{self.role}')>"


class ScoreSuggestion(Base):
    """An AI-proposed Pareto score awaiting the user's accept/edit/reject (D23)."""

    __tablename__ = "score_suggestions"

    id = Column(String, primary_key=True)
    project_id = Column(String, index=True, nullable=False)
    feature_id = Column(String, index=True, nullable=False)
    current_impact = Column(Integer)
    current_effort = Column(Integer)
    current_risk = Column(Integer)
    suggested_impact = Column(Integer)
    suggested_effort = Column(Integer)
    suggested_risk = Column(Integer)
    rationale = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    status = Column(String, default="pending", index=True)  # pending|accepted|rejected
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<ScoreSuggestion(feature='{self.feature_id}', status='{self.status}')>"
