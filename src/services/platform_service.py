"""
Scale, ecosystem & ritual (100-Day Roadmap, Phase 10: D94-D100).

Most of this phase is composition rather than new machinery: the ritual flow,
the recommendations, and the admin console all read subsystems that already
exist. The two genuinely new pieces are a language setting that reaches every
generation prompt, and an in-app help index built over Dobby's own docs.

**In-app help retrieves over the shipped Markdown docs, not a bundled
embedding index.** The docs directory is right there, it changes with every
release, and lexical retrieval over it needs no model pulled — the same
reasoning as the copilot's retrieval, for the same reason.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.db.idea_models import Idea
from src.db.planning_models import FeatureStatusChange, PlanningMeta
from src.db.schema import DatabaseManager, FeatureBacklog, Node, Project

logger = structlog.get_logger()

# Languages the generation flows offer. Kept explicit rather than free text so
# the UI can list them and a typo cannot silently produce English.
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese", "it": "Italian", "nl": "Dutch", "hi": "Hindi",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Simplified)",
    "ar": "Arabic", "ru": "Russian",
}

# A curated catalog rather than the whole Ollama registry: the useful thing is
# guidance on what actually fits a given machine, which an unfiltered list of
# thousands of tags does not give.
MODEL_CATALOG = [
    {"id": "llama3.2:1b", "size_gb": 1.3, "ram_gb": 4, "blurb": "Tiny and fast. Good for chat and summaries.", "tags": ["chat", "summarize"]},
    {"id": "llama3.2", "size_gb": 2.0, "ram_gb": 8, "blurb": "The sensible default for most work.", "tags": ["generate", "chat"]},
    {"id": "llama3.1:8b", "size_gb": 4.7, "ram_gb": 16, "blurb": "Stronger reasoning for document drafts.", "tags": ["generate"]},
    {"id": "qwen2.5:7b", "size_gb": 4.4, "ram_gb": 16, "blurb": "Strong at structured output and JSON.", "tags": ["generate", "prioritize"]},
    {"id": "qwen2.5-coder:7b", "size_gb": 4.4, "ram_gb": 16, "blurb": "Best for pseudocode and TDD artifacts.", "tags": ["generate"]},
    {"id": "mistral", "size_gb": 4.1, "ram_gb": 16, "blurb": "Fast general-purpose alternative.", "tags": ["generate", "chat"]},
    {"id": "phi3", "size_gb": 2.2, "ram_gb": 8, "blurb": "Small but capable at reasoning.", "tags": ["chat", "prioritize"]},
    {"id": "nomic-embed-text", "size_gb": 0.3, "ram_gb": 4, "blurb": "Embeddings, if you enable semantic search.", "tags": ["embed"]},
]

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"

STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is",
             "are", "how", "what", "do", "i", "my", "can", "it", "does", "with"}

# A single incidental body mention scores 0.5. Requiring more than that keeps
# help from confidently citing a section that merely happens to share a common
# word with the question — a wrong-but-plausible answer is worse than "I don't
# know", especially for help text people consult when already confused.
MIN_HELP_SCORE = 1.0


class PlatformError(Exception):
    pass


# ---------------------------------------------------------------------------
# i18n (D94)
# ---------------------------------------------------------------------------
def get_language() -> Dict[str, str]:
    from src.settings import get_settings

    code = getattr(get_settings(), "output_language", "en") or "en"
    return {"code": code, "name": LANGUAGES.get(code, "English")}


def set_language(code: str) -> Dict[str, str]:
    if code not in LANGUAGES:
        raise PlatformError(f"Unsupported language. One of: {', '.join(sorted(LANGUAGES))}")
    from src.settings import get_settings_store

    get_settings_store().update(output_language=code)
    return {"code": code, "name": LANGUAGES[code]}


def language_instruction() -> str:
    """The line appended to generation prompts. Empty for English, so the
    default path is byte-identical to what it was before this feature."""
    code = get_language()["code"]
    if code == "en":
        return ""
    return (f"\n\nWrite the entire response in {LANGUAGES[code]}. "
            "Keep code identifiers, file paths, and proper nouns unchanged.")


# ---------------------------------------------------------------------------
# Model catalog (D95)
# ---------------------------------------------------------------------------
def _total_ram_gb() -> float:
    try:
        import subprocess

        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                             timeout=5)
        if out.returncode == 0:
            return round(int(out.stdout.decode().strip()) / (1024 ** 3), 1)
    except Exception:
        pass
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1)
    except Exception:
        return 0.0


async def model_catalog() -> Dict[str, Any]:
    """The catalog, annotated with what is installed and what this machine fits."""
    installed: List[str] = []
    try:
        from src.llm.ollama_client import OllamaClient

        client = OllamaClient()
        models = await client.list_models()
        installed = [m.get("name", m) if isinstance(m, dict) else str(m)
                     for m in (models or [])]
    except Exception:
        # Ollama being down is not an error here — the catalog is still useful.
        installed = []

    ram = _total_ram_gb()
    entries = []
    for m in MODEL_CATALOG:
        is_installed = any(str(i).split(":")[0] == m["id"].split(":")[0] and
                           (":" not in m["id"] or str(i) == m["id"])
                           for i in installed)
        entries.append({
            **m,
            "installed": is_installed,
            "fits": (ram >= m["ram_gb"]) if ram else None,
            "pull_command": f"ollama pull {m['id']}",
        })

    return {"models": entries, "system_ram_gb": ram,
            "ollama_reachable": bool(installed),
            "note": "Models are pulled by Ollama itself; Dobby never downloads on your behalf."}


# ---------------------------------------------------------------------------
# In-app help (D99)
# ---------------------------------------------------------------------------
def _doc_files() -> List[Path]:
    if not DOCS_DIR.exists():
        return []
    return sorted(p for p in DOCS_DIR.rglob("*.md") if p.is_file())


def _sections(text: str, source: str) -> List[Dict[str, str]]:
    """Split a doc into heading-delimited chunks so answers cite a section."""
    chunks, heading, buf = [], "", []
    for line in text.split("\n"):
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if buf:
                chunks.append({"source": source, "heading": heading,
                               "text": "\n".join(buf).strip()})
            heading, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if buf:
        chunks.append({"source": source, "heading": heading,
                       "text": "\n".join(buf).strip()})
    return [c for c in chunks if c["text"]]


def search_help(question: str, limit: int = 5) -> Dict[str, Any]:
    """Lexical retrieval over Dobby's own shipped documentation."""
    terms = [w for w in re.findall(r"[a-z0-9]+", (question or "").lower())
             if len(w) > 2 and w not in STOPWORDS]
    if not terms:
        return {"hits": [], "searched": 0}

    scored = []
    searched = 0
    for path in _doc_files():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(DOCS_DIR.parent))
        for chunk in _sections(text, rel):
            searched += 1
            haystack = (chunk["heading"] + " " + chunk["text"]).lower()
            score = 0.0
            for t in set(terms):
                if t in chunk["heading"].lower():
                    score += 3.0
                score += min(haystack.count(t), 5) * 0.5
            if score >= MIN_HELP_SCORE:
                scored.append((score, chunk))

    scored.sort(key=lambda x: (-x[0], x[1]["source"]))
    hits = [{"source": c["source"], "heading": c["heading"],
             "snippet": c["text"][:700], "score": round(s, 2)}
            for s, c in scored[:limit]]
    return {"hits": hits, "searched": searched}


async def answer_help(db: DatabaseManager, question: str,
                      model: str = "") -> Dict[str, Any]:
    """Answer a question about Dobby, grounded in its own docs."""
    found = search_help(question, limit=4)
    if not found["hits"]:
        return {"answer": ("I could not find that in Dobby's documentation. "
                           "Try the User Guide in docs/USER_GUIDE.md."),
                "sources": [], "grounded": False}

    context = "\n\n".join(f"[{i + 1}] {h['source']} — {h['heading']}\n{h['snippet']}"
                          for i, h in enumerate(found["hits"]))

    from src.services import model_routing

    prompt = (
        "Answer this question about the Dobby app using ONLY the documentation below.\n\n"
        f"Documentation:\n---\n{context}\n---\n\n"
        f"Question: {question}\n\n"
        "Cite sources as [1], [2]. If the documentation does not answer it, say so."
    )

    try:
        answer = await model_routing.call(db, "chat", prompt, model=model,
                                          max_tokens=800, temperature=0.2)
    except Exception:
        # A local model being unavailable must not make help unusable — the
        # retrieved sections are already the answer, just unsummarised.
        return {"answer": "", "sources": found["hits"], "grounded": True,
                "model_unavailable": True}

    return {"answer": (answer or "").strip(), "sources": found["hits"],
            "grounded": True, "model_unavailable": False}


# ---------------------------------------------------------------------------
# Guided goals (D98)
# ---------------------------------------------------------------------------
GUIDED_GOALS = [
    {
        "slug": "mvp_spec_set", "name": "Ship an MVP spec set",
        "blurb": "A complete, verified document set for your first feature.",
        "steps": [
            {"key": "capture", "label": "Capture the idea", "route": "/ideas"},
            {"key": "backlog", "label": "Get it into the backlog", "route": "/backlog"},
            {"key": "generate", "label": "Generate the documents", "route": "/yolo"},
            {"key": "review", "label": "Send a document to review", "route": "/documents"},
            {"key": "approve", "label": "Approve it", "route": "/documents"},
        ],
    },
    {
        "slug": "daily_habit", "name": "Build the daily habit",
        "blurb": "Use Dobby seven days running.",
        "steps": [
            {"key": "capture", "label": "Capture an idea", "route": "/ideas"},
            {"key": "streak_3", "label": "Reach a 3-day streak", "route": "/"},
            {"key": "streak_7", "label": "Reach a 7-day streak", "route": "/"},
            {"key": "pin", "label": "Pin what you're working on", "route": "/ideas"},
        ],
    },
    {
        "slug": "plan_a_sprint", "name": "Plan and run a sprint",
        "blurb": "Take work from backlog to done with real numbers behind it.",
        "steps": [
            {"key": "estimate", "label": "Estimate some work", "route": "/board"},
            {"key": "sprint", "label": "Create a sprint", "route": "/board"},
            {"key": "in_progress", "label": "Start something", "route": "/board"},
            {"key": "done", "label": "Finish something", "route": "/board"},
        ],
    },
]


def goal_progress(db: DatabaseManager, project_id: str) -> List[Dict[str, Any]]:
    """Step state derived from real data, never stored — same rule as onboarding."""
    from src.db.document_models import DocumentMeta
    from src.db.pin_models import Pin
    from src.db.planning_models import Sprint
    from src.services import momentum_service

    with db.get_session() as s:
        has_idea = s.query(Idea).filter(Idea.project_id == project_id).count() > 0
        has_feature = (s.query(FeatureBacklog)
                       .filter(FeatureBacklog.project_id == project_id).count() > 0)
        has_node = s.query(Node).filter(Node.project_id == project_id).count() > 0
        in_review = (s.query(DocumentMeta)
                     .filter(DocumentMeta.project_id == project_id,
                             DocumentMeta.status.in_(("in_review", "approved"))).count() > 0)
        approved = (s.query(DocumentMeta)
                    .filter(DocumentMeta.project_id == project_id,
                            DocumentMeta.status == "approved").count() > 0)
        has_pin = s.query(Pin).filter(Pin.project_id == project_id).count() > 0
        has_sprint = s.query(Sprint).filter(Sprint.project_id == project_id).count() > 0
        has_estimate = (s.query(PlanningMeta)
                        .filter(PlanningMeta.project_id == project_id,
                                PlanningMeta.estimate.isnot(None)).count() > 0)
        started = (s.query(FeatureStatusChange)
                   .filter(FeatureStatusChange.project_id == project_id,
                           FeatureStatusChange.to_column == "in_progress").count() > 0)
        finished = (s.query(FeatureStatusChange)
                    .filter(FeatureStatusChange.project_id == project_id,
                            FeatureStatusChange.to_column == "done").count() > 0)

    streak = momentum_service.get_momentum(db, project_id)["streak"]

    done_map = {
        "capture": has_idea, "backlog": has_feature, "generate": has_node,
        "review": in_review, "approve": approved,
        "streak_3": streak >= 3, "streak_7": streak >= 7, "pin": has_pin,
        "estimate": has_estimate, "sprint": has_sprint,
        "in_progress": started, "done": finished,
    }

    out = []
    for goal in GUIDED_GOALS:
        steps = [{**st, "done": bool(done_map.get(st["key"], False))}
                 for st in goal["steps"]]
        complete = sum(1 for st in steps if st["done"])
        out.append({
            "slug": goal["slug"], "name": goal["name"], "blurb": goal["blurb"],
            "steps": steps, "completed": complete, "total": len(steps),
            "percent": round(100.0 * complete / len(steps), 1) if steps else 0.0,
            "next_step": next((st for st in steps if not st["done"]), None),
        })
    return out


# ---------------------------------------------------------------------------
# Recommendations (D97)
# ---------------------------------------------------------------------------
async def recommendations(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """Suggestions grounded in what this machine and this project actually show."""
    recs: List[Dict[str, str]] = []

    catalog = await model_catalog()
    ram = catalog["system_ram_gb"]
    installed = [m for m in catalog["models"] if m["installed"]]
    if not installed:
        recs.append({"kind": "model",
                     "title": "Pull a model to get started",
                     "detail": "Nothing is installed yet. `ollama pull llama3.2` is the sensible default.",
                     "route": "/settings"})
    elif ram:
        bigger = [m for m in catalog["models"]
                  if not m["installed"] and m["fits"] and m["ram_gb"] >= 16
                  and "generate" in m["tags"]]
        if bigger:
            recs.append({"kind": "model",
                         "title": f"Your machine can run {bigger[0]['id']}",
                         "detail": f"{ram}GB RAM. {bigger[0]['blurb']}",
                         "route": "/settings"})

    from src.services import model_telemetry

    usage = model_telemetry.usage(db, project_id, days=14)
    slow = [t for t in usage["by_task"] if t["avg_ms"] > 20000]
    if slow:
        recs.append({"kind": "routing",
                     "title": f"“{slow[0]['task_type']}” is slow at {slow[0]['avg_ms'] // 1000}s",
                     "detail": "Route it to a smaller model in Settings — chat rarely needs your largest one.",
                     "route": "/usage"})

    goals = goal_progress(db, project_id)
    unfinished = [g for g in goals if g["percent"] < 100 and g["next_step"]]
    if unfinished:
        g = min(unfinished, key=lambda x: -x["percent"])
        recs.append({"kind": "goal",
                     "title": f"{g['name']} — {g['completed']}/{g['total']} done",
                     "detail": f"Next: {g['next_step']['label']}",
                     "route": g["next_step"]["route"]})

    with db.get_session() as s:
        untriaged = (s.query(Idea).filter(Idea.project_id == project_id,
                                          Idea.status == "inbox").count())
    if untriaged >= 5:
        recs.append({"kind": "template",
                     "title": f"{untriaged} ideas waiting",
                     "detail": "Merge near-duplicates first — it usually cuts the pile.",
                     "route": "/ideas"})

    return {"recommendations": recs, "count": len(recs)}


# ---------------------------------------------------------------------------
# Admin console (D96)
# ---------------------------------------------------------------------------
def admin_console(db: DatabaseManager) -> Dict[str, Any]:
    """Cross-project aggregate. Local-first: it reads this machine only."""
    from src.services import model_telemetry

    with db.get_session() as s:
        projects = s.query(Project).all()
        rows = []
        for p in projects:
            rows.append({
                "project_id": p.id, "name": p.name,
                "documents": s.query(Node).filter(Node.project_id == p.id).count(),
                "features": (s.query(FeatureBacklog)
                             .filter(FeatureBacklog.project_id == p.id).count()),
                "completed": (s.query(FeatureBacklog)
                              .filter(FeatureBacklog.project_id == p.id,
                                      FeatureBacklog.status == "completed").count()),
                "ideas": s.query(Idea).filter(Idea.project_id == p.id).count(),
            })

    usage = model_telemetry.usage(db, None, days=30)
    rows.sort(key=lambda r: -r["documents"])

    return {
        "projects": rows,
        "project_count": len(rows),
        "totals": {
            "documents": sum(r["documents"] for r in rows),
            "features": sum(r["features"] for r in rows),
            "completed": sum(r["completed"] for r in rows),
            "ideas": sum(r["ideas"] for r in rows),
        },
        "model_usage": {
            "calls": usage["total_calls"], "tokens": usage["total_tokens"],
            "avg_ms": usage["avg_ms"], "failures": usage["failures"],
            "estimated_cost": usage["estimated_cost"],
        },
        "scope": "This machine only — Dobby aggregates nothing off-device.",
    }


# ---------------------------------------------------------------------------
# Ritual mode (D100)
# ---------------------------------------------------------------------------
async def start_your_day(db: DatabaseManager, project_id: str) -> Dict[str, Any]:
    """The single guided flow that ties the whole app together."""
    from src.services import habit_service, home_service, momentum_service, nba_service

    momentum = momentum_service.get_momentum(db, project_id)
    home = home_service.build_home(db, project_id)
    next_action = await nba_service.next_best_action(db, project_id, phrase=False)
    memories = habit_service.on_this_day(db, project_id)
    goals = goal_progress(db, project_id)
    recs = await recommendations(db, project_id)

    from src.services import planning_service

    plan = planning_service.propose_daily_plan(db, project_id)

    steps = [
        {"key": "review", "title": "What's waiting",
         "count": len(home.get("needs_triage", [])) + len(home.get("needs_decision", [])),
         "route": "/"},
        {"key": "focus", "title": "Do this first",
         "detail": next_action["message"],
         "route": next_action["suggestion"]["route"] if next_action["suggestion"] else "/"},
        {"key": "plan", "title": "Today's plan",
         "count": len(plan["proposed"]), "route": "/board"},
    ]
    if memories["memories"]:
        steps.append({"key": "remember", "title": "On this day",
                      "detail": memories["memories"][0]["title"], "route": "/"})

    return {
        "greeting": home.get("greeting", "Hello"),
        "streak": momentum["streak"],
        "active_today": momentum["active_today"],
        "steps": steps,
        "plan": plan["proposed"],
        "goals": [g for g in goals if g["percent"] < 100][:2],
        "recommendations": recs["recommendations"][:2],
        "clear": home.get("clear", False),
    }
