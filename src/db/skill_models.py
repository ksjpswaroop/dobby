"""
Skills — one saved thing binding intent, sources, guardrails and approval
(Work Graph, step 3).

Every part of a skill already existed and none of it was connected. The
prompt library held intent. MCP and attachments held sources. Content safety
and the capability model held guardrails. The Inbox held approval. A user
could configure all four and still had no object called "the thing I do".

A `Skill` is that object. It is **declarative** — a prompt, a list of allowed
sources, a set of limits, an approval mode — and never code, for the same
reason custom verification rules are not code: an app that imports archives
from other people cannot also execute what those archives contain.

The seven-artifact generator becomes a built-in Skill rather than being
replaced by this. It is the most valuable thing Dobby does; making it one
skill among many is a promotion of the frame, not a demotion of the feature.
"""

from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)

from src.db.schema import Base

# Where a skill may read from. Each maps to a subsystem that already enforces
# its own rules — this list is what the user *permits*, not a new mechanism.
SOURCE_KINDS = (
    "project_documents",   # nodes in this project
    "project_backlog",     # features and their scores
    "research_briefs",     # completed research
    "attachments",         # uploaded files
    "web_search",          # only if a provider is enabled in Settings
    "mcp_tools",           # connected MCP servers
)

# Approval modes, in increasing order of trust. `manual` is the default
# because a skill the user has not watched run yet should not act alone.
APPROVAL_MODES = ("manual", "unattended_reads", "unattended")

# What a skill is allowed to do with its output.
OUTPUT_ACTIONS = ("return_only", "save_document", "capture_idea", "create_decision")

SKILL_STATES = ("draft", "published")


class Skill(Base):
    """A saved capability: intent + sources + guardrails + approval."""

    __tablename__ = "skills"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), index=True)
    slug = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    state = Column(String, nullable=False, default="draft", index=True)

    # --- 1. Intent ---------------------------------------------------------
    # The prompt itself, or a reference to one in the prompt library. Storing
    # the body inline keeps a published skill stable when the library changes.
    prompt = Column(Text, default="")
    prompt_id = Column(String)
    goal = Column(Text, default="")
    expected_output = Column(Text, default="")

    # --- 2. Sources --------------------------------------------------------
    sources = Column(JSON, default=list)          # subset of SOURCE_KINDS
    excluded_sources = Column(JSON, default=list)  # stated exclusions

    # --- 3. Guardrails -----------------------------------------------------
    # Free-text rules shown to the model, plus hard limits enforced in code.
    rules = Column(JSON, default=list)
    max_output_words = Column(Integer, default=0)   # 0 = no limit
    forbid_placeholders = Column(Integer, default=1)
    local_only = Column(Integer, default=1)         # refuse network sources

    # --- 4. Review ---------------------------------------------------------
    approval_mode = Column(String, nullable=False, default="manual")
    output_action = Column(String, nullable=False, default="return_only")
    output_params = Column(JSON, default=dict)

    builtin = Column(Integer, default=0)
    run_count = Column(Integer, default=0)
    last_run_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_skill_slug"),
        Index("idx_skills_project_state", "project_id", "state"),
    )

    def __repr__(self):
        return f"<Skill(slug='{self.slug}', state='{self.state}')>"


class SkillRun(Base):
    """One execution, including simulations.

    Simulations are recorded too: "what would this have done" is exactly the
    thing worth keeping, and a dry run that vanishes teaches nobody anything.
    """

    __tablename__ = "skill_runs"

    id = Column(String, primary_key=True)
    skill_id = Column(String, ForeignKey("skills.id"), index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    input_text = Column(Text, default="")
    output_text = Column(Text, default="")
    simulated = Column(Integer, default=0, index=True)
    ok = Column(Integer, default=1)
    error = Column(Text)
    # [{step, detail, ok}] — what the run actually did, in order.
    trace = Column(JSON, default=list)
    # What the output became, when the skill was permitted to act.
    produced_type = Column(String)
    produced_id = Column(String)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (Index("idx_skillruns_skill_created", "skill_id", "created_at"),)
