"""
The Research pipeline — the stage that runs *before* Create.

Flow per brief:

    plan  →  for each of five tracks:  queries → search → learnings
                                              ↘ review → (one more round)
          →  synthesize each track  →  executive summary  →  candidate features

Tracks run **concurrently** because they are independent investigations; within
a track the rounds are sequential because each one decides what the next should
look for.

Everything is traced through the existing `Tracer`, so a research pass shows up
in Logs & Traces and streams to the UI over the same SSE channel as generation.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.db.research_models import (
    TRACK_KINDS, TRACK_LABELS, ResearchBrief, ResearchLearning, ResearchSource,
    ResearchTrack,
)
from src.db.schema import DatabaseManager, FeatureBacklog, Project
from src.llm.ollama_client import get_ollama_client
from src.observability.tracer import Tracer
from src.services import research_prompts as P
from src.services import research_search as S

logger = structlog.get_logger()

MAX_ROUNDS = 2          # initial pass + at most one follow-up per track
QUERIES_PER_ROUND = 3
MAX_LEARNINGS = 12


class ResearchError(Exception):
    """Research could not start — surfaced as a 4xx/503 rather than a crash."""


# ---------------------------------------------------------------------------
# Parsing helpers — small models ignore formatting instructions often enough
# that every parser here has to tolerate stray numbering, bullets, and prose.
# ---------------------------------------------------------------------------
_LEAD = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s*")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _lines(text: str, limit: int) -> List[str]:
    out: List[str] = []
    in_fence = False
    for raw in (text or "").splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = _LEAD.sub("", raw).strip().strip('"').strip()
        # Drop conversational filler a small model prepends.
        if not line or line.endswith(":") or len(line) < 8:
            continue
        out.append(line[:600])
        if len(out) >= limit:
            break
    return out


# A statistic is a number with units, a percentage, a currency amount, or a
# scale word. Bare years and small counts are not — those are rarely the kind of
# invented figure that misleads.
_STAT = re.compile(
    r"(\$\s?\d[\d,.]*\s*(?:[KMB]|million|billion|trillion)?"
    r"|\d[\d,.]*\s*%"
    r"|\b\d[\d,.]*\s*(?:million|billion|trillion|users|customers|companies)\b"
    r"|\bCAGR\b)",
    re.I,
)
_MARKED = re.compile(r"^\s*\[(?:inferred|estimate[d]?|unverified)]", re.I)


def _flag_unverified(text: str, grounded: bool) -> str:
    """Mark a finding that states a statistic without evidence to back it.

    The prompts ask the model never to invent figures and to tag inference.
    Small models comply inconsistently — in live testing llama3.2 produced a
    market size and a survey percentage as bare fact. Since a fabricated
    statistic is the most damaging thing a research tool can emit, this adds a
    mechanical backstop on top of the instruction: with no search provider
    configured, any unmarked statistic gets tagged.
    """
    if grounded or _MARKED.match(text) or not _STAT.search(text):
        return text
    return f"[unverified] {text}"


def _section(markdown: str, heading: str) -> str:
    """Pull one `## Heading` section out of the plan."""
    pattern = re.compile(
        rf"^#{{1,4}}\s*{re.escape(heading)}\s*$(.*?)(?=^#{{1,4}}\s|\Z)",
        re.M | re.S | re.I,
    )
    m = pattern.search(markdown or "")
    return m.group(1).strip() if m else ""


def _evidence_block(outcomes: List[S.SearchOutcome]) -> Tuple[str, List[S.SearchResult]]:
    """Render search hits for the prompt, and return them for source records."""
    hits: List[S.SearchResult] = []
    for o in outcomes:
        hits.extend(o.results)
    if not hits:
        return "", []
    parts = [
        f'<result index="{i + 1}" url="{h.url}">\n{h.title}\n{h.snippet}\n</result>'
        for i, h in enumerate(hits)
    ]
    return "\n".join(parts), hits


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def _project_context(db: DatabaseManager, project_id: str) -> str:
    with db.get_session() as s:
        p = s.get(Project, project_id)
        if not p:
            return ""
        bits = [f"Project: {p.name}"]
        if p.idea:
            bits.append(f"Idea: {p.idea}")
        return "\n".join(bits)


def _search_config() -> Tuple[str, Dict[str, str]]:
    from src.settings import get_settings

    s = get_settings()
    provider = getattr(s, "search_provider", "none") or "none"
    cfg = {
        "searxng_url": getattr(s, "searxng_url", "") or "",
        "tavily_api_key": getattr(s, "tavily_api_key", "") or "",
        "brave_api_key": getattr(s, "brave_api_key", "") or "",
    }
    return provider, cfg


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def create_brief(db: DatabaseManager, project_id: str, topic: str,
                 context: str = "") -> Dict[str, Any]:
    topic = (topic or "").strip()
    if not topic:
        raise ResearchError("Give the research a topic.")

    provider, _ = _search_config()
    brief_id = str(uuid.uuid4())
    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise ResearchError("Project not found.")
        s.add(ResearchBrief(
            id=brief_id, project_id=project_id, topic=topic[:500],
            context=(context or "")[:4000], status="pending",
            search_provider=provider,
        ))
        for i, kind in enumerate(TRACK_KINDS):
            s.add(ResearchTrack(id=str(uuid.uuid4()), brief_id=brief_id,
                                kind=kind, sort_order=i))
        s.commit()
    return get_brief(db, brief_id)


def get_brief(db: DatabaseManager, brief_id: str) -> Optional[Dict[str, Any]]:
    with db.get_session() as s:
        b = s.get(ResearchBrief, brief_id)
        if not b:
            return None
        tracks = (s.query(ResearchTrack)
                  .filter(ResearchTrack.brief_id == brief_id)
                  .order_by(ResearchTrack.sort_order).all())
        learnings = (s.query(ResearchLearning)
                     .filter(ResearchLearning.brief_id == brief_id)
                     .order_by(ResearchLearning.sort_order).all())
        sources = (s.query(ResearchSource)
                   .filter(ResearchSource.brief_id == brief_id).all())
        return {
            "id": b.id, "project_id": b.project_id, "topic": b.topic,
            "context": b.context, "status": b.status, "plan": b.plan,
            "summary": b.summary, "search_provider": b.search_provider,
            "error": b.error, "run_id": b.run_id,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "tracks": [{
                "kind": t.kind, "label": TRACK_LABELS.get(t.kind, t.kind),
                "status": t.status, "content": t.content,
                "confidence": t.confidence, "error": t.error,
                "learnings": [
                    {"id": l.id, "content": l.content,
                     "promoted_feature_id": l.promoted_feature_id}
                    for l in learnings if l.track_kind == t.kind
                ],
            } for t in tracks],
            "sources": [{"kind": s_.kind, "title": s_.title, "url": s_.url,
                         "track_kind": s_.track_kind} for s_ in sources],
        }


def list_briefs(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    with db.get_session() as s:
        rows = (s.query(ResearchBrief)
                .filter(ResearchBrief.project_id == project_id)
                .order_by(ResearchBrief.created_at.desc()).limit(50).all())
        return [{"id": b.id, "topic": b.topic, "status": b.status,
                 "search_provider": b.search_provider,
                 "created_at": b.created_at.isoformat() if b.created_at else None}
                for b in rows]


def delete_brief(db: DatabaseManager, brief_id: str) -> bool:
    with db.get_session() as s:
        b = s.get(ResearchBrief, brief_id)
        if not b:
            return False
        for model in (ResearchLearning, ResearchSource, ResearchTrack):
            s.query(model).filter(model.brief_id == brief_id).delete(
                synchronize_session=False)
        s.delete(b)
        s.commit()
    return True


def _set_brief(db: DatabaseManager, brief_id: str, **fields) -> None:
    with db.get_session() as s:
        b = s.get(ResearchBrief, brief_id)
        if not b:
            return
        for k, v in fields.items():
            setattr(b, k, v)
        b.updated_at = datetime.utcnow()
        s.commit()


def _set_track(db: DatabaseManager, brief_id: str, kind: str, **fields) -> None:
    with db.get_session() as s:
        t = (s.query(ResearchTrack)
             .filter(ResearchTrack.brief_id == brief_id,
                     ResearchTrack.kind == kind).first())
        if not t:
            return
        for k, v in fields.items():
            setattr(t, k, v)
        t.updated_at = datetime.utcnow()
        s.commit()


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
async def _ask(client, prompt: str, *, max_tokens: int = 1200,
               temperature: float = 0.4) -> str:
    return await client.generate(prompt, max_tokens=max_tokens,
                                 temperature=temperature) or ""


async def _run_track(db: DatabaseManager, client, brief_id: str, topic: str,
                     kind: str, plan: str, provider: str, cfg: Dict[str, str],
                     tracer: Tracer) -> None:
    """One track: queries → search → learnings → review → synthesize."""
    label = TRACK_LABELS[kind]
    focus = _section(plan, label) or P.TRACK_BRIEFS[kind]
    _set_track(db, brief_id, kind, status="researching")

    learnings: List[str] = []
    all_hits: List[S.SearchResult] = []
    search_note: Optional[str] = None
    queries: List[str] = []

    for round_no in range(MAX_ROUNDS):
        if round_no == 0:
            raw = await _ask(client, P.queries_prompt(topic, label, plan,
                                                      QUERIES_PER_ROUND),
                             max_tokens=300, temperature=0.5)
            queries = _lines(raw, QUERIES_PER_ROUND)
        # round 1's queries come from the review step below

        outcomes = await S.search_many(queries, provider, cfg) if queries else []
        for o in outcomes:
            if o.error and not search_note:
                search_note = o.error
        evidence, hits = _evidence_block(outcomes)
        all_hits.extend(hits)
        grounded = bool(hits)

        raw = await _ask(client,
                         P.learnings_prompt(topic, label, focus, evidence, grounded),
                         max_tokens=1400, temperature=0.4)
        new = [_flag_unverified(l, grounded)
               for l in _lines(raw, MAX_LEARNINGS) if l not in learnings]
        learnings.extend(new)
        tracer.event("track.round", f"{label}: {len(learnings)} findings",
                     track=kind, round=round_no + 1, sources=len(hits))

        if round_no + 1 >= MAX_ROUNDS or not learnings:
            break
        review = await _ask(client, P.review_prompt(topic, label, focus, learnings),
                            max_tokens=200, temperature=0.3)
        if "COMPLETE" in review.upper():
            break
        queries = _lines(review, 2)
        if not queries:
            break

    if not learnings:
        _set_track(db, brief_id, kind, status="failed",
                   error="The model produced no usable findings for this track.")
        return

    grounded = bool(all_hits)
    content = await _ask(client,
                         P.synthesis_prompt(topic, label, focus, learnings, grounded),
                         max_tokens=1800, temperature=0.45)
    if not content.strip():
        content = "## " + label + "\n\n" + "\n".join(f"- {l}" for l in learnings)

    with db.get_session() as s:
        for i, text in enumerate(learnings[:MAX_LEARNINGS]):
            s.add(ResearchLearning(id=str(uuid.uuid4()), brief_id=brief_id,
                                   track_kind=kind, content=text, sort_order=i))
        seen = set()
        for h in all_hits:
            if h.url in seen:
                continue
            seen.add(h.url)
            s.add(ResearchSource(id=str(uuid.uuid4()), brief_id=brief_id,
                                 track_kind=kind, kind="web",
                                 title=h.title[:300], url=h.url[:1000],
                                 snippet=h.snippet[:1000]))
        if not all_hits:
            s.add(ResearchSource(id=str(uuid.uuid4()), brief_id=brief_id,
                                 track_kind=kind, kind="model",
                                 title="Model knowledge (no web search)",
                                 snippet=search_note or ""))
        s.commit()

    _set_track(db, brief_id, kind, status="complete", content=content.strip(),
               error=search_note)
    tracer.event("track.done", f"{label} complete", advance=True,
                 track=kind, findings=len(learnings), sources=len(all_hits))


async def run_brief(db: DatabaseManager, brief_id: str) -> Dict[str, Any]:
    """Execute a research brief end to end."""
    brief = get_brief(db, brief_id)
    if not brief:
        raise ResearchError("Research brief not found.")
    if brief["status"] in ("planning", "researching", "synthesizing"):
        raise ResearchError("This research is already running.")

    from src.settings import get_settings

    settings = get_settings()
    topic, project_id = brief["topic"], brief["project_id"]
    provider, cfg = _search_config()

    try:
        client = await get_ollama_client(base_url=settings.ollama_host,
                                         model=settings.model)
    except Exception as e:
        _set_brief(db, brief_id, status="failed", error=str(e))
        raise ResearchError(f"Cannot reach Ollama: {e}")

    tracer = Tracer(db, kind="research", label=topic[:80],
                    project_id=project_id, model=settings.model,
                    total_steps=len(TRACK_KINDS) + 2)
    _set_brief(db, brief_id, run_id=tracer.run_id, status="planning",
               model=settings.model, search_provider=provider, error=None)

    try:
        # 1. Plan
        tracer.event("plan.start", "Planning the research")
        plan = await _ask(
            client,
            P.plan_prompt(topic, brief["context"], _project_context(db, project_id)),
            max_tokens=1200, temperature=0.4,
        )
        _set_brief(db, brief_id, plan=plan.strip(), status="researching")
        tracer.event("plan.done", "Plan ready")

        # 2. Tracks, concurrently — they are independent investigations.
        await asyncio.gather(*(
            _run_track(db, client, brief_id, topic, kind, plan, provider, cfg, tracer)
            for kind in TRACK_KINDS
        ))

        # 3. Summary
        _set_brief(db, brief_id, status="synthesizing")
        final = get_brief(db, brief_id)
        sections = "\n\n".join(t["content"] for t in final["tracks"] if t["content"])
        if not sections.strip():
            raise ResearchError("No track produced any output.")
        summary = await _ask(client, P.summary_prompt(topic, sections),
                             max_tokens=600, temperature=0.4)
        _set_brief(db, brief_id, summary=summary.strip(), status="complete")
        tracer.event("summary.done", "Research complete")
        tracer.finish("ok")
    except Exception as e:
        logger.exception("research_failed", brief_id=brief_id)
        _set_brief(db, brief_id, status="failed", error=str(e)[:500])
        tracer.finish("failed", error=str(e))
        raise
    finally:
        await client.close()

    return get_brief(db, brief_id)


# ---------------------------------------------------------------------------
# Research → Create
# ---------------------------------------------------------------------------
_FEATURE_LINE = re.compile(r"^(.+?)\|(.+?)\|(.*?)\|(.*?)\|(.*)$")


def _score(text: str, default: float = 5.0) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    if not m:
        return default
    return _clamp(m.group())


def _clamp(value: Any, default: float = 5.0) -> float:
    """Coerce a model-supplied score into the backlog's 1-10 range."""
    try:
        return max(1.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return default


async def propose_features(db: DatabaseManager, brief_id: str) -> List[Dict[str, Any]]:
    """Turn a completed brief into candidate backlog features.

    Proposals only — nothing is written to the backlog until the user accepts,
    for the same reason AI regroup only proposes: research is a suggestion, and
    a backlog silently filling itself would be worse than useless.
    """
    brief = get_brief(db, brief_id)
    if not brief:
        raise ResearchError("Research brief not found.")
    if brief["status"] != "complete":
        raise ResearchError("Finish the research before proposing features.")

    from src.settings import get_settings

    settings = get_settings()
    sections = "\n\n".join(t["content"] for t in brief["tracks"] if t["content"])
    try:
        client = await get_ollama_client(base_url=settings.ollama_host,
                                         model=settings.model)
    except Exception as e:
        raise ResearchError(f"Cannot reach Ollama: {e}")
    try:
        raw = await _ask(client, P.features_prompt(brief["topic"], sections),
                         max_tokens=1200, temperature=0.5)
    finally:
        await client.close()

    out: List[Dict[str, Any]] = []
    for line in _lines(raw, 12):
        m = _FEATURE_LINE.match(line)
        if not m:
            continue
        title = m.group(1).strip(" *_`#")[:200]
        if not title:
            continue
        out.append({
            "title": title,
            "description": m.group(2).strip()[:1000],
            "impact": _score(m.group(3), 5.0),
            "effort": _score(m.group(4), 5.0),
            "risk": _score(m.group(5), 5.0),
        })
    return out


def accept_features(db: DatabaseManager, brief_id: str,
                    features: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write accepted proposals into the feature backlog."""
    brief = get_brief(db, brief_id)
    if not brief:
        raise ResearchError("Research brief not found.")

    from src.pipeline.pareto import ParetoScorer

    scorer = ParetoScorer(db)
    created = 0
    with db.get_session() as s:
        for f in features:
            title = str(f.get("title") or "").strip()
            if not title:
                continue
            # The backlog stores these as 1-10 integers.
            impact = int(round(_clamp(f.get("impact"))))
            effort = int(round(_clamp(f.get("effort"))))
            risk = int(round(_clamp(f.get("risk"))))
            s.add(FeatureBacklog(
                id=str(uuid.uuid4()), project_id=brief["project_id"],
                title=title[:200], description=str(f.get("description") or "")[:2000],
                impact_score=impact, effort_score=effort, risk_score=risk,
                pareto_score=scorer.calculate_pareto_score(impact, effort, risk),
                status="backlog",
                # No dedicated column for provenance; metadata keeps the link
                # back to the research that justified this feature.
                extra_metadata={"source": "research", "brief_id": brief_id,
                                "topic": brief["topic"]},
            ))
            created += 1
        s.commit()

    logger.info("research_features_accepted", brief_id=brief_id, created=created)
    return {"success": True, "created": created}
