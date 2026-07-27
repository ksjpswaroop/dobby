"""
Skills — running a saved capability (Work Graph, step 3).

`run()` is the whole module. It walks the four parts of a skill in order and
records what each did, which is what makes a "run simulation" honest: the
trace is the same shape whether or not anything was actually written.

Three properties hold regardless of how a skill is configured:

**Guardrails are enforced in code, not requested in the prompt.** A word
limit stated in a prompt is a suggestion; `max_output_words` is a check.
Likewise `local_only` refuses a web source outright rather than asking the
model not to use one.

**Acting requires approval.** Anything beyond returning text — saving a
document, capturing an idea, creating a decision — goes through the Inbox
gate unless the user has explicitly moved the skill to `unattended`. A skill
that writes on its first run before anyone has watched it is exactly the
thing that makes people turn automation off.

**A simulation writes nothing.** It runs intent and guardrails for real,
then reports what the output *would* have become.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.skill_models import (
    APPROVAL_MODES, OUTPUT_ACTIONS, SKILL_STATES, SOURCE_KINDS, Skill, SkillRun,
)
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project

logger = structlog.get_logger()

CONTEXT_CHARS = 6000

# Sources that leave the machine. `local_only` refuses exactly these.
NETWORK_SOURCES = {"web_search"}

BUILTIN_SKILLS = [
    {
        "slug": "seven_artifact_set",
        "name": "Seven-artifact document set",
        "description": ("Dobby's core generator: a complete, verified engineering "
                        "document set from one feature idea."),
        "goal": "Turn a feature idea into Feature Spec, User Stories, Functional "
                "Analysis, Flowchart, Pseudocode, TDD Tests, and Documentation.",
        "expected_output": "Seven linked documents, each passing deterministic verification.",
        "prompt": ("Generate a complete engineering document set for: {{input}}\n\n"
                   "Project context:\n{{context}}\n\n"
                   "Produce each of the seven artifacts with clear section headings."),
        "sources": ["project_documents", "project_backlog"],
        "rules": ["No placeholder text.", "Every section must be specific to this feature.",
                  "Prefer concrete detail over generic advice."],
        "output_action": "save_document",
        "approval_mode": "manual",
    },
    {
        "slug": "research_to_evidence",
        "name": "Research-to-Evidence",
        "description": "Turn research into cited, decision-ready evidence.",
        "goal": "Answer a focused question with evidence from credible sources.",
        "expected_output": "Evidence brief with citations and a confidence summary.",
        "prompt": ("Answer this question using only the sources below:\n\n{{input}}\n\n"
                   "Sources:\n{{context}}\n\n"
                   "Cite each claim as [1], [2]. State plainly what you could not verify."),
        "sources": ["project_documents", "research_briefs"],
        "rules": ["No fabrication.", "Prefer primary sources.", "Note uncertainty explicitly."],
        "output_action": "return_only",
        "approval_mode": "manual",
    },
    {
        "slug": "decision_brief",
        "name": "Decision brief",
        "description": "Frame an open question as a decision with real options.",
        "goal": "Turn a fuzzy question into a decision with two or three viable branches.",
        "expected_output": "A titled decision, its options, and the trade-off between them.",
        "prompt": ("Frame this as a decision:\n\n{{input}}\n\n"
                   "Context:\n{{context}}\n\n"
                   "Give a one-line title, then 2-3 genuinely viable options with the "
                   "trade-off each one accepts. Do not recommend one."),
        "sources": ["project_documents", "project_backlog"],
        "rules": ["Options must be genuinely viable — no straw men.",
                  "Do not pick for the user."],
        "output_action": "create_decision",
        "approval_mode": "manual",
    },
]


class SkillError(Exception):
    pass


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:60]


def _skill_dict(sk: Skill) -> Dict[str, Any]:
    return {
        "id": sk.id, "project_id": sk.project_id, "slug": sk.slug, "name": sk.name,
        "description": sk.description, "state": sk.state,
        "goal": sk.goal, "expected_output": sk.expected_output,
        "prompt": sk.prompt, "prompt_id": sk.prompt_id,
        "sources": sk.sources or [], "excluded_sources": sk.excluded_sources or [],
        "rules": sk.rules or [],
        "max_output_words": sk.max_output_words or 0,
        "forbid_placeholders": bool(sk.forbid_placeholders),
        "local_only": bool(sk.local_only),
        "approval_mode": sk.approval_mode,
        "output_action": sk.output_action,
        "output_params": sk.output_params or {},
        "builtin": bool(sk.builtin),
        "run_count": sk.run_count or 0,
        "last_run_at": sk.last_run_at.isoformat() if sk.last_run_at else None,
        # What this skill may and may not do, in the user's words. The Skill
        # Studio shows this verbatim so permissions are never a surprise.
        "permissions": _permissions(sk),
    }


def _permissions(sk: Skill) -> Dict[str, List[str]]:
    can, cannot = [], []
    labels = {
        "project_documents": "Read your project documents",
        "project_backlog": "Read your backlog",
        "research_briefs": "Read your research",
        "attachments": "Read your uploaded files",
        "web_search": "Search the web",
        "mcp_tools": "Use connected tools",
    }
    for s in (sk.sources or []):
        can.append(labels.get(s, s))
    for s in SOURCE_KINDS:
        if s not in (sk.sources or []):
            cannot.append(labels.get(s, s))

    if sk.output_action == "return_only":
        cannot.append("Make any changes")
    else:
        action = {"save_document": "Save a document",
                  "capture_idea": "Capture an idea",
                  "create_decision": "Create a decision"}[sk.output_action]
        can.append(action + (" (with your approval)"
                             if sk.approval_mode == "manual" else ""))

    cannot.append("Run code or install anything")
    if sk.local_only:
        cannot.append("Send your data anywhere")
    return {"can": can, "cannot": cannot}


# ---------------------------------------------------------------------------
# Validation & CRUD
# ---------------------------------------------------------------------------
def _validate(sources: List[str], approval_mode: str, output_action: str,
              local_only: bool) -> None:
    unknown = [s for s in sources if s not in SOURCE_KINDS]
    if unknown:
        raise SkillError(f"Unknown sources: {', '.join(unknown)}. "
                         f"One of: {', '.join(SOURCE_KINDS)}")
    if approval_mode not in APPROVAL_MODES:
        raise SkillError(f"Unknown approval mode. One of: {', '.join(APPROVAL_MODES)}")
    if output_action not in OUTPUT_ACTIONS:
        raise SkillError(f"Unknown output action. One of: {', '.join(OUTPUT_ACTIONS)}")
    if local_only and (set(sources) & NETWORK_SOURCES):
        raise SkillError(
            "This skill is marked local-only but lists a source that leaves the "
            "machine. Turn off local-only, or remove the web source.")


def create(db: DatabaseManager, project_id: str, name: str, prompt: str,
           description: str = "", goal: str = "", expected_output: str = "",
           sources: Optional[List[str]] = None, rules: Optional[List[str]] = None,
           approval_mode: str = "manual", output_action: str = "return_only",
           output_params: Optional[Dict[str, Any]] = None,
           max_output_words: int = 0, local_only: bool = True) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise SkillError("A skill needs a name.")
    if not (prompt or "").strip():
        raise SkillError("A skill needs a prompt — that is its intent.")

    sources = sources or []
    _validate(sources, approval_mode, output_action, local_only)

    slug = _slugify(name)
    if not slug:
        raise SkillError("That name has no usable characters.")

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise SkillError("Project not found.")
        if s.query(Skill).filter(Skill.project_id == project_id,
                                 Skill.slug == slug).first():
            raise SkillError(f"A skill '{slug}' already exists in this project.")
        sk = Skill(
            id=str(uuid.uuid4()), project_id=project_id, slug=slug, name=name[:120],
            description=description[:2000], state="draft",
            prompt=prompt, goal=goal[:1000], expected_output=expected_output[:1000],
            sources=sources, rules=rules or [],
            approval_mode=approval_mode, output_action=output_action,
            output_params=output_params or {},
            max_output_words=max(0, int(max_output_words or 0)),
            local_only=1 if local_only else 0,
        )
        s.add(sk)
        s.commit()
        return _skill_dict(sk)


def update(db: DatabaseManager, skill_id: str, **changes: Any) -> Dict[str, Any]:
    with db.get_session() as s:
        sk = s.get(Skill, skill_id)
        if not sk:
            raise SkillError("Skill not found.")
        if sk.builtin:
            raise SkillError("Built-in skills cannot be edited — fork one instead.")

        sources = changes.get("sources", sk.sources or [])
        approval = changes.get("approval_mode", sk.approval_mode)
        action = changes.get("output_action", sk.output_action)
        local_only = changes.get("local_only", bool(sk.local_only))
        _validate(list(sources), approval, action, bool(local_only))

        for field in ("name", "description", "prompt", "goal", "expected_output",
                      "sources", "excluded_sources", "rules", "approval_mode",
                      "output_action", "output_params", "max_output_words"):
            if field in changes and changes[field] is not None:
                setattr(sk, field, changes[field])
        if "local_only" in changes:
            sk.local_only = 1 if changes["local_only"] else 0
        if "forbid_placeholders" in changes:
            sk.forbid_placeholders = 1 if changes["forbid_placeholders"] else 0
        sk.updated_at = datetime.utcnow()
        s.commit()
        return _skill_dict(sk)


def publish(db: DatabaseManager, skill_id: str) -> Dict[str, Any]:
    """Move a skill out of draft. Requires it to have been simulated first."""
    with db.get_session() as s:
        sk = s.get(Skill, skill_id)
        if not sk:
            raise SkillError("Skill not found.")
        simulated = (s.query(SkillRun)
                     .filter(SkillRun.skill_id == skill_id,
                             SkillRun.simulated == 1, SkillRun.ok == 1).count())
        if not simulated:
            # Publishing something nobody has watched run once is how an
            # automation surface loses trust on its first real use.
            raise SkillError("Run a simulation before publishing, so you can see "
                             "what this skill actually does.")
        sk.state = "published"
        sk.updated_at = datetime.utcnow()
        s.commit()
        return _skill_dict(sk)


def get(db: DatabaseManager, skill_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        sk = s.get(Skill, skill_id)
        return _skill_dict(sk) if sk else None


def list_skills(db: DatabaseManager, project_id: str,
                state: Optional[str] = None) -> List[Dict[str, Any]]:
    if state and state not in SKILL_STATES:
        raise SkillError(f"Unknown state. One of: {', '.join(SKILL_STATES)}")
    with db.get_session() as s:
        q = s.query(Skill).filter((Skill.project_id == project_id)
                                  | (Skill.project_id.is_(None)))
        if state:
            q = q.filter(Skill.state == state)
        rows = q.all()
        rows.sort(key=lambda x: (bool(x.builtin), x.name or ""))
        return [_skill_dict(sk) for sk in rows]


def delete(db: DatabaseManager, skill_id: str) -> bool:
    with db.get_session() as s:
        sk = s.get(Skill, skill_id)
        if not sk:
            return False
        if sk.builtin:
            raise SkillError("Built-in skills cannot be deleted.")
        for r in s.query(SkillRun).filter(SkillRun.skill_id == skill_id).all():
            s.delete(r)
        s.flush()
        s.delete(sk)
        s.commit()
        return True


def fork(db: DatabaseManager, skill_id: str, project_id: str) -> Dict[str, Any]:
    with db.get_session() as s:
        src = s.get(Skill, skill_id)
        if not src:
            raise SkillError("Skill not found.")
        base = f"{src.slug}_fork"
        slug, n = base, 2
        while s.query(Skill).filter(Skill.project_id == project_id,
                                    Skill.slug == slug).first():
            slug = f"{base}{n}"
            n += 1
        sk = Skill(
            id=str(uuid.uuid4()), project_id=project_id, slug=slug,
            name=f"{src.name} (fork)", description=src.description, state="draft",
            prompt=src.prompt, goal=src.goal, expected_output=src.expected_output,
            sources=list(src.sources or []), rules=list(src.rules or []),
            approval_mode=src.approval_mode, output_action=src.output_action,
            output_params=dict(src.output_params or {}),
            max_output_words=src.max_output_words,
            forbid_placeholders=src.forbid_placeholders, local_only=src.local_only,
            builtin=0,
        )
        s.add(sk)
        s.commit()
        return _skill_dict(sk)


def seed_builtins(db: DatabaseManager) -> int:
    """Insert missing built-in skills. Idempotent — safe on every boot."""
    added = 0
    with db.get_session() as s:
        for spec in BUILTIN_SKILLS:
            if s.query(Skill).filter(Skill.project_id.is_(None),
                                     Skill.slug == spec["slug"]).first():
                continue
            s.add(Skill(
                id=str(uuid.uuid4()), project_id=None, slug=spec["slug"],
                name=spec["name"], description=spec["description"], state="published",
                prompt=spec["prompt"], goal=spec["goal"],
                expected_output=spec["expected_output"],
                sources=spec["sources"], rules=spec["rules"],
                approval_mode=spec["approval_mode"],
                output_action=spec["output_action"], builtin=1, local_only=1,
            ))
            added += 1
        s.commit()
    return added


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def _gather_context(db: DatabaseManager, project_id: str,
                    sources: List[str]) -> tuple:
    """Read only what the skill is permitted to read."""
    parts, used = [], []

    with db.get_session() as s:
        if "project_documents" in sources:
            nodes = s.query(Node).filter(Node.project_id == project_id).limit(8).all()
            if nodes:
                used.append("project_documents")
                parts.append("\n\n".join(f"### {n.title}\n{(n.content or '')[:600]}"
                                         for n in nodes))
        if "project_backlog" in sources:
            feats = (s.query(FeatureBacklog)
                     .filter(FeatureBacklog.project_id == project_id)
                     .order_by(FeatureBacklog.pareto_score.desc()).limit(10).all())
            if feats:
                used.append("project_backlog")
                parts.append("Backlog:\n" + "\n".join(
                    f"- {f.title} (pareto {f.pareto_score:.2f})" for f in feats))
        if "research_briefs" in sources:
            from src.db.research_models import ResearchBrief

            briefs = (s.query(ResearchBrief)
                      .filter(ResearchBrief.project_id == project_id,
                              ResearchBrief.status == "complete").limit(3).all())
            if briefs:
                used.append("research_briefs")
                parts.append("\n\n".join(f"### Research: {b.topic}\n{(b.summary or '')[:600]}"
                                         for b in briefs))

    return "\n\n".join(parts)[:CONTEXT_CHARS], used


async def run(db: DatabaseManager, skill_id: str, input_text: str = "",
              simulate: bool = False, model: str = "") -> Dict[str, Any]:
    """Run a skill through its four parts, recording what each did."""
    with db.get_session() as s:
        sk = s.get(Skill, skill_id)
        if not sk:
            raise SkillError("Skill not found.")
        project_id = sk.project_id
        snapshot = _skill_dict(sk)

    if not project_id:
        # Built-ins are project-less templates; they run against a project.
        raise SkillError("Fork this built-in into a project before running it.")

    started = time.monotonic()
    trace: List[Dict[str, Any]] = []
    output, error, ok = "", "", True
    produced_type = produced_id = None

    # 1. Sources
    context, used = _gather_context(db, project_id, snapshot["sources"])
    trace.append({"step": "sources", "ok": True,
                  "detail": f"read {', '.join(used) or 'nothing'}"})

    # 2. Intent
    prompt = (snapshot["prompt"]
              .replace("{{input}}", input_text or "")
              .replace("{{context}}", context or "(no context available)"))
    if snapshot["rules"]:
        prompt += "\n\nRules:\n" + "\n".join(f"- {r}" for r in snapshot["rules"])

    try:
        from src.services import model_routing

        output = await model_routing.call(db, "generate", prompt, model=model,
                                          project_id=project_id, max_tokens=2000,
                                          temperature=0.4)
        trace.append({"step": "intent", "ok": True,
                      "detail": f"{len(output.split())} words generated"})
    except Exception as e:
        ok, error = False, str(e)[:400]
        trace.append({"step": "intent", "ok": False, "detail": error})

    # 3. Guardrails
    if ok:
        failures = _check_guardrails(snapshot, output)
        if failures:
            ok = False
            error = "; ".join(failures)
            trace.append({"step": "guardrails", "ok": False, "detail": error})
        else:
            trace.append({"step": "guardrails", "ok": True, "detail": "passed"})

    # 4. Review / act
    if ok:
        action = snapshot["output_action"]
        if action == "return_only":
            trace.append({"step": "review", "ok": True,
                          "detail": "returns text only — nothing to approve"})
        elif simulate:
            trace.append({"step": "review", "ok": True,
                          "detail": f"simulation — would have run '{action}'"})
        else:
            approved = True
            if snapshot["approval_mode"] == "manual":
                from src.services import inbox_service

                try:
                    decision = await inbox_service.require(
                        db, project_id, "file.write", f"skill:{snapshot['slug']}",
                        title=f"Let “{snapshot['name']}” {action.replace('_', ' ')}?",
                        detail=(f"The skill produced {len(output.split())} words and "
                                f"wants to {action.replace('_', ' ')}."),
                        risk="medium")
                    approved = decision in ("allowed", "approved")
                except Exception as e:
                    approved = False
                    error = f"approval failed: {e}"[:300]

            if not approved:
                ok = False
                error = error or "Not approved."
                trace.append({"step": "review", "ok": False, "detail": error})
            else:
                produced_type, produced_id = _perform(db, project_id, snapshot, output)
                trace.append({"step": "review", "ok": True,
                              "detail": f"{action.replace('_', ' ')} — {produced_type}"})

    duration = int((time.monotonic() - started) * 1000)

    with db.get_session() as s:
        run_row = SkillRun(
            id=str(uuid.uuid4()), skill_id=skill_id, project_id=project_id,
            input_text=(input_text or "")[:4000], output_text=output[:20000],
            simulated=1 if simulate else 0, ok=1 if ok else 0, error=error or None,
            trace=trace, produced_type=produced_type, produced_id=produced_id,
            duration_ms=duration,
        )
        s.add(run_row)
        sk = s.get(Skill, skill_id)
        if sk and not simulate:
            sk.run_count = (sk.run_count or 0) + 1
            sk.last_run_at = datetime.utcnow()
        s.commit()
        run_id = run_row.id

    return {
        "run_id": run_id, "skill": {"id": skill_id, "name": snapshot["name"]},
        "ok": ok, "simulated": simulate, "output": output, "error": error or None,
        "trace": trace, "duration_ms": duration,
        "produced": {"type": produced_type, "id": produced_id} if produced_id else None,
    }


def _check_guardrails(snapshot: Dict[str, Any], output: str) -> List[str]:
    """Enforced in code — a limit stated in a prompt is only a suggestion."""
    failures = []
    limit = snapshot.get("max_output_words") or 0
    words = len(output.split())
    if limit and words > limit:
        failures.append(f"Output is {words} words, limit is {limit}.")
    if snapshot.get("forbid_placeholders"):
        for marker in ("TODO", "TBD", "FIXME", "Lorem ipsum"):
            if marker.lower() in output.lower():
                failures.append(f"Output contains placeholder text: {marker}")
                break
    return failures


def _perform(db: DatabaseManager, project_id: str, snapshot: Dict[str, Any],
             output: str) -> tuple:
    action = snapshot["output_action"]
    params = snapshot.get("output_params") or {}

    if action == "save_document":
        node_id = str(uuid.uuid4())
        with db.get_session() as s:
            s.add(Node(id=node_id, project_id=project_id,
                       node_type=params.get("node_type") or "documentation",
                       title=(params.get("title") or snapshot["name"])[:200],
                       content=output, status="draft"))
            s.commit()
        return "document", node_id

    if action == "capture_idea":
        from src.services import idea_service

        idea = idea_service.capture(db, project_id, output[:4000])
        return "idea", idea["id"]

    if action == "create_decision":
        from src.services import decision_service

        # The first line is the title; remaining bullets become options.
        lines = [l.strip() for l in output.split("\n") if l.strip()]
        title = re.sub(r"^#+\s*", "", lines[0])[:300] if lines else snapshot["name"]
        options = [{"label": re.sub(r"^[-*+]\s*", "", l)[:200]}
                   for l in lines[1:] if re.match(r"^[-*+]\s+", l)][:4]
        d = decision_service.create(db, project_id, title, output[:4000],
                                    options=options)
        return "decision", d["id"]

    return None, None


def list_runs(db: DatabaseManager, skill_id: str,
              limit: int = 20) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(SkillRun).filter(SkillRun.skill_id == skill_id)
                .order_by(SkillRun.created_at.desc()).limit(limit).all())
        return [{
            "id": r.id, "ok": bool(r.ok), "simulated": bool(r.simulated),
            "error": r.error, "trace": r.trace or [],
            "duration_ms": r.duration_ms,
            "produced": {"type": r.produced_type, "id": r.produced_id}
            if r.produced_id else None,
            "output_preview": (r.output_text or "")[:400],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]
