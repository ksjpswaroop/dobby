"""
Prompt library (100-Day Roadmap, Day 27).

Built-ins are seeded as rows rather than kept in code so that forking, diffing
against the original, and resetting all work through one mechanism. A fork
records `forked_from`, which is what makes "show me what I changed" and
"reset to Dobby's version" possible at all.

Variables are declared as `{{name}}` and validated before a render, so a
prompt with a typo'd placeholder fails loudly at edit time instead of quietly
sending the model a literal `{{contxt}}`.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional

from src.db.copilot_models import PromptTemplate
from src.db.schema import DatabaseManager

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

BUILTINS = [
    {
        "slug": "feature_spec",
        "name": "Feature Spec",
        "task_type": "generate",
        "description": "The built-in prompt for generating a feature specification.",
        "body": (
            "Write a feature specification for: {{feature}}\n\n"
            "Project context: {{context}}\n\n"
            "Include these sections: Overview, Problem, Solution, User Impact, "
            "Technical Considerations. Be concrete and avoid filler."
        ),
    },
    {
        "slug": "user_stories",
        "name": "User Stories",
        "task_type": "generate",
        "description": "Generates user stories with acceptance criteria.",
        "body": (
            "Write user stories for: {{feature}}\n\n"
            "Context: {{context}}\n\n"
            "Use the form 'As a <role>, I want <goal>, so that <benefit>.' "
            "Give each story acceptance criteria."
        ),
    },
    {
        "slug": "summarize_document",
        "name": "Summarize a document",
        "task_type": "summarize",
        "description": "Condenses any document to what matters.",
        "body": (
            "Summarize this document titled \"{{title}}\".\n\n---\n{{content}}\n---\n\n"
            "Give 3-5 bullets capturing what actually matters. Markdown only."
        ),
    },
    {
        "slug": "prioritize_feature",
        "name": "Score a feature",
        "task_type": "prioritize",
        "description": "Proposes impact/effort/risk for a backlog item.",
        "body": (
            "Estimate scores 1-10 for: {{feature}}\n\nDescription: {{description}}\n\n"
            'Return only JSON: {"impact": n, "effort": n, "risk": n, '
            '"confidence": 0.0, "rationale": "..."}'
        ),
    },
    {
        "slug": "chat_grounded",
        "name": "Grounded project chat",
        "task_type": "chat",
        "description": "Answers questions using only retrieved project documents.",
        "body": (
            "Documents:\n---\n{{context}}\n---\n\nQuestion: {{question}}\n\n"
            "Answer using ONLY the documents above, citing them as [1], [2]. "
            "If they do not contain the answer, say so."
        ),
    },
]


class PromptError(Exception):
    pass


def declared_variables(body: str) -> List[str]:
    seen, out = set(), []
    for m in VAR_RE.finditer(body or ""):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _dict(t: PromptTemplate) -> Dict[str, Any]:
    return {
        "id": t.id, "slug": t.slug, "name": t.name, "description": t.description,
        "body": t.body, "variables": t.variables or [], "task_type": t.task_type,
        "builtin": bool(t.builtin), "forked_from": t.forked_from, "version": t.version,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def seed_builtins(db: DatabaseManager) -> int:
    """Insert any missing built-ins. Idempotent — safe to call on every boot."""
    added = 0
    with db.get_session() as s:
        for spec in BUILTINS:
            exists = (s.query(PromptTemplate)
                      .filter(PromptTemplate.project_id.is_(None),
                              PromptTemplate.slug == spec["slug"]).first())
            if exists:
                continue
            s.add(PromptTemplate(
                id=str(uuid.uuid4()), project_id=None, slug=spec["slug"],
                name=spec["name"], description=spec["description"], body=spec["body"],
                variables=declared_variables(spec["body"]),
                task_type=spec["task_type"], builtin=1,
            ))
            added += 1
        s.commit()
    return added


def list_prompts(db: DatabaseManager,
                 project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Built-ins plus this project's own, built-ins last so forks lead."""
    with db.get_session() as s:
        rows = (s.query(PromptTemplate)
                .filter((PromptTemplate.project_id == project_id)
                        | (PromptTemplate.project_id.is_(None)))
                .all())
        rows.sort(key=lambda t: (bool(t.builtin), t.name or ""))
        return [_dict(t) for t in rows]


def get_prompt(db: DatabaseManager, prompt_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        t = s.get(PromptTemplate, prompt_id)
        return _dict(t) if t else None


def create_prompt(db: DatabaseManager, project_id: str, name: str, body: str,
                  task_type: str = "other", description: str = "") -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise PromptError("A prompt needs a name.")
    if not (body or "").strip():
        raise PromptError("A prompt needs a body.")
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    if not slug:
        raise PromptError("That name has no usable characters.")

    with db.get_session() as s:
        if s.query(PromptTemplate).filter(PromptTemplate.project_id == project_id,
                                          PromptTemplate.slug == slug).first():
            raise PromptError(f"A prompt '{slug}' already exists in this project.")
        t = PromptTemplate(
            id=str(uuid.uuid4()), project_id=project_id, slug=slug, name=name[:120],
            description=description[:1000], body=body, task_type=task_type,
            variables=declared_variables(body), builtin=0,
        )
        s.add(t)
        s.commit()
        return _dict(t)


def fork_prompt(db: DatabaseManager, prompt_id: str, project_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        src = s.get(PromptTemplate, prompt_id)
        if not src:
            raise PromptError("Prompt not found.")
        slug = f"{src.slug}_fork"
        n = 2
        while s.query(PromptTemplate).filter(PromptTemplate.project_id == project_id,
                                             PromptTemplate.slug == slug).first():
            slug = f"{src.slug}_fork{n}"
            n += 1
        t = PromptTemplate(
            id=str(uuid.uuid4()), project_id=project_id, slug=slug,
            name=f"{src.name} (fork)", description=src.description, body=src.body,
            variables=list(src.variables or []), task_type=src.task_type,
            builtin=0, forked_from=src.id,
        )
        s.add(t)
        s.commit()
        return _dict(t)


def update_prompt(db: DatabaseManager, prompt_id: str, body: Optional[str] = None,
                  name: Optional[str] = None,
                  description: Optional[str] = None) -> Dict[str, Any]:
    with db.get_session() as s:
        t = s.get(PromptTemplate, prompt_id)
        if not t:
            raise PromptError("Prompt not found.")
        if t.builtin:
            raise PromptError("Built-in prompts cannot be edited — fork it first.")
        if body is not None:
            t.body = body
            t.variables = declared_variables(body)
        if name:
            t.name = name[:120]
        if description is not None:
            t.description = description[:1000]
        t.version = (t.version or 1) + 1
        s.commit()
        return _dict(t)


def delete_prompt(db: DatabaseManager, prompt_id: str) -> bool:
    with db.get_session() as s:
        t = s.get(PromptTemplate, prompt_id)
        if not t:
            return False
        if t.builtin:
            raise PromptError("Built-in prompts cannot be deleted.")
        s.delete(t)
        s.commit()
        return True


def render(db: DatabaseManager, prompt_id: str,
           values: Dict[str, str]) -> Dict[str, Any]:
    """Substitute variables, refusing rather than sending a half-filled prompt."""
    with db.get_session() as s:
        t = s.get(PromptTemplate, prompt_id)
        if not t:
            raise PromptError("Prompt not found.")
        body, declared = t.body, declared_variables(t.body)

    missing = [v for v in declared if v not in values or values[v] is None]
    if missing:
        raise PromptError(f"Missing values for: {', '.join(missing)}")

    rendered = body
    for name, value in values.items():
        rendered = VAR_RE.sub(
            lambda m, n=name, v=value: str(v) if m.group(1) == n else m.group(0),
            rendered,
        )
    return {"rendered": rendered, "variables": declared}


def diff_against_origin(db: DatabaseManager, prompt_id: str) -> Dict[str, Any]:
    """What a fork changed relative to the built-in it came from."""
    import difflib

    with db.get_session() as s:
        t = s.get(PromptTemplate, prompt_id)
        if not t:
            raise PromptError("Prompt not found.")
        if not t.forked_from:
            raise PromptError("This prompt is not a fork.")
        origin = s.get(PromptTemplate, t.forked_from)
        if not origin:
            raise PromptError("The original prompt no longer exists.")
        diff = list(difflib.unified_diff(
            (origin.body or "").split("\n"), (t.body or "").split("\n"),
            fromfile="original", tofile="fork", lineterm="",
        ))
        return {"diff": diff, "origin_id": origin.id, "origin_name": origin.name}
