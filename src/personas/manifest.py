"""
Persona manifests (OW rows 26-32 — Next Task 9).

A persona is a named way of working: a system prompt, the capabilities it is
allowed to use, the model shape it wants, and the connections it recommends.
Switching persona changes how Dobby behaves without changing what it is.

The manifest is **markdown with YAML-ish frontmatter**, per OW row 27, because
a persona is mostly prose and prose belongs in a format a human edits happily.
The parser is hand-written rather than pulling in PyYAML: the schema is small
and fixed, and a full YAML parser on third-party input is a larger attack
surface than this feature justifies.

    ---
    name: Ops
    description: Runs and watches things.
    capabilities: [shell.execute, automation.run]
    model_capabilities: [local, long_context]
    recommends: [wigolo, filesystem]
    permission_mode: unattended
    ---

    You are an operations assistant. Prefer checking over guessing…

The body after the frontmatter is the system prompt.

**Capabilities are a ceiling, not a grant.** A persona listing `shell.execute`
means "this persona may ask for shell access", never "shell access is
approved". The Inbox still decides. A persona that could widen permissions by
declaring them would make installing a third-party persona a privilege
escalation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# Capabilities a persona may declare. Anything else is dropped with a warning
# rather than honoured — an unknown capability is a typo or an attack.
from src.db.inbox_models import CAPABILITIES

VALID_MODES = ("ask", "unattended", "readonly")
MAX_PROMPT = 20_000

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
_LIST_INLINE = re.compile(r"^\[(.*)\]$")


class ManifestError(ValueError):
    """An invalid persona manifest. Message is user-facing."""


@dataclass
class Persona:
    id: str
    name: str
    description: str = ""
    system_prompt: str = ""
    capabilities: List[str] = field(default_factory=list)
    model_capabilities: List[str] = field(default_factory=list)
    recommends: List[str] = field(default_factory=list)
    permission_mode: str = "ask"
    builtin: bool = False
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "system_prompt": self.system_prompt,
            "capabilities": self.capabilities,
            "model_capabilities": self.model_capabilities,
            "recommends": self.recommends,
            "permission_mode": self.permission_mode,
            "builtin": self.builtin, "source": self.source,
        }


def _parse_scalar(raw: str) -> Any:
    value = raw.strip().strip('"').strip("'")
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def _parse_list(raw: str) -> List[str]:
    raw = raw.strip()
    inline = _LIST_INLINE.match(raw)
    if inline:
        raw = inline.group(1)
    return [p.strip().strip('"').strip("'") for p in raw.split(",") if p.strip()]


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """A deliberately small key: value parser.

    Supports scalars and inline `[a, b]` lists, which is the whole schema. A
    real YAML parser would accept far more than this format needs, on input
    that may come from a third party.
    """
    out: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if key in ("capabilities", "model_capabilities", "recommends"):
            out[key] = _parse_list(value)
        else:
            out[key] = _parse_scalar(value)
    return out


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "persona"


def parse(text: str, source: str = "", builtin: bool = False) -> Persona:
    """Parse a manifest, dropping anything it is not entitled to declare."""
    if not (text or "").strip():
        raise ManifestError("The persona file is empty.")

    match = _FRONTMATTER.match(text.strip())
    if not match:
        raise ManifestError(
            "A persona needs a `---` frontmatter block with at least a `name`, "
            "followed by the system prompt."
        )
    meta = _parse_frontmatter(match.group(1))
    body = (match.group(2) or "").strip()

    name = str(meta.get("name") or "").strip()
    if not name:
        raise ManifestError("The persona is missing a `name`.")
    if not body:
        raise ManifestError(
            "The persona has no system prompt — put it after the frontmatter."
        )

    declared = [c for c in (meta.get("capabilities") or []) if isinstance(c, str)]
    allowed, rejected = [], []
    for c in declared:
        (allowed if c in CAPABILITIES else rejected).append(c)
    if rejected:
        # Dropped rather than honoured: an unknown capability is a typo or an
        # attempt to invent one.
        logger.warning("persona_unknown_capabilities", name=name, dropped=rejected)

    mode = str(meta.get("permission_mode") or "ask").strip().lower()
    if mode not in VALID_MODES:
        mode = "ask"

    return Persona(
        id=_slug(str(meta.get("id") or name)),
        name=name[:100],
        description=str(meta.get("description") or "")[:500],
        system_prompt=body[:MAX_PROMPT],
        capabilities=allowed,
        model_capabilities=[str(c) for c in (meta.get("model_capabilities") or [])],
        recommends=[str(c) for c in (meta.get("recommends") or [])],
        permission_mode=mode,
        builtin=builtin,
        source=source,
    )


def render(persona: Persona) -> str:
    """Serialise back to a manifest, so a persona can be edited and shared."""
    def fmt(items: List[str]) -> str:
        return "[" + ", ".join(items) + "]"

    lines = [
        "---",
        f"name: {persona.name}",
        f"description: {persona.description}",
        f"capabilities: {fmt(persona.capabilities)}",
        f"model_capabilities: {fmt(persona.model_capabilities)}",
        f"recommends: {fmt(persona.recommends)}",
        f"permission_mode: {persona.permission_mode}",
        "---",
        "",
        persona.system_prompt,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Built-ins (OW row 26)
# ---------------------------------------------------------------------------
BUILTIN_MANIFESTS: List[str] = [
    """---
name: Dobby
description: The general assistant. Balanced, asks before acting.
capabilities: [net.fetch, file.write]
model_capabilities: [local]
recommends: [wigolo]
permission_mode: ask
---

You are Dobby, a careful product assistant working entirely on the user's own
machine.

- Prefer what you can verify to what sounds right. Say when you are inferring.
- Be concrete: name tools, numbers, and trade-offs rather than describing them.
- The user is an expert. Do not pad or restate their question back to them.
- Never invent a statistic, a source, or a URL.
""",
    """---
name: Researcher
description: Digs into a subject and reports what is actually true.
capabilities: [net.fetch]
model_capabilities: [local, long_context]
recommends: [wigolo]
permission_mode: ask
---

You are a research analyst. Your output is judged on whether its claims hold up.

- Separate what a source says from what you infer from it, every time.
- Prefer a specific claim you can defend to a general one that sounds safe.
- Name entities: companies, products, standards, dates, figures.
- When evidence is thin, say what would settle the question instead of guessing.
""",
    """---
name: Engineer
description: Reads and writes code, runs things, checks its work.
capabilities: [shell.execute, file.write, net.fetch]
model_capabilities: [local, tools]
recommends: [filesystem, wigolo]
permission_mode: ask
---

You are a software engineer working in this project.

- Read the surrounding code before changing it; match its conventions.
- Prefer the smallest change that solves the actual problem.
- Run the tests. Report failures with their output rather than summarising.
- When a command could be destructive, explain what it does before proposing it.
""",
    """---
name: Ops
description: Runs scheduled work and watches for things going wrong.
capabilities: [shell.execute, automation.run, net.fetch]
model_capabilities: [local]
recommends: [wigolo]
permission_mode: unattended
---

You are an operations assistant running mostly unattended.

- Check rather than assume. A stale reading is worse than no reading.
- Report state changes, not steady state — nobody needs "still fine" hourly.
- Escalate anything ambiguous instead of choosing for the user.
- Keep summaries to what a person can act on.
""",
]


def builtins() -> List[Persona]:
    out = []
    for text in BUILTIN_MANIFESTS:
        try:
            out.append(parse(text, source="builtin", builtin=True))
        except ManifestError as e:  # a broken built-in is a bug, not user error
            logger.error("builtin_persona_invalid", error=str(e))
    return out
