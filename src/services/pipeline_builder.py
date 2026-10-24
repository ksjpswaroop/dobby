"""
Composable pipelines (100-Day Roadmap, Day 92).

A pipeline is an ordered list of steps that transform a payload: generate,
verify, transform, filter, fan out. Users compose them from a fixed step
catalogue rather than by writing code — the same reasoning as the custom
verification rules. A builder that executes user-supplied code would be a
remote-execution hole in an app that also imports archives from other people.

The execution model is deliberately linear with an explicit context dict
rather than a general graph. A DAG needs cycle detection, topological
ordering, and a story for partial failure; a linear chain needs none of that,
and every pipeline anyone actually described in the roadmap is a chain.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager, Node, Project

logger = structlog.get_logger()

# The step catalogue. Each entry declares its inputs so the builder UI can
# validate a pipeline before it is ever run.
STEP_TYPES: Dict[str, Dict[str, Any]] = {
    "generate": {
        "label": "Generate text",
        "params": ["prompt", "model"],
        "description": "Run a prompt through the local model. {{input}} is the payload.",
    },
    "verify": {
        "label": "Verify",
        "params": ["min_words", "require_sections", "forbid_placeholders"],
        "description": "Deterministic checks. Fails the run if the document does not pass.",
    },
    "transform": {
        "label": "Transform text",
        "params": ["operation"],
        "description": "upper | lower | strip | collapse_blank_lines | strip_placeholders",
    },
    "filter": {
        "label": "Filter",
        "params": ["contains", "not_contains", "min_words"],
        "description": "Stop the pipeline unless the payload matches.",
    },
    "save_document": {
        "label": "Save as a document",
        "params": ["title", "node_type"],
        "description": "Write the payload into the project as a new document.",
    },
    "capture_idea": {
        "label": "Capture as an idea",
        "params": [],
        "description": "Write the payload into the Idea Inbox.",
    },
}

TRANSFORMS = ("upper", "lower", "strip", "collapse_blank_lines", "strip_placeholders")

MAX_STEPS = 20


class PipelineError(Exception):
    pass


def validate(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate a pipeline before it can be saved or run."""
    if not steps:
        raise PipelineError("A pipeline needs at least one step.")
    if len(steps) > MAX_STEPS:
        raise PipelineError(f"A pipeline can have at most {MAX_STEPS} steps.")

    cleaned = []
    for i, step in enumerate(steps):
        kind = step.get("type")
        if kind not in STEP_TYPES:
            raise PipelineError(
                f"Step {i + 1}: unknown type '{kind}'. "
                f"One of: {', '.join(STEP_TYPES)}")
        params = dict(step.get("params") or {})

        if kind == "generate" and not str(params.get("prompt", "")).strip():
            raise PipelineError(f"Step {i + 1}: a generate step needs a prompt.")
        if kind == "transform":
            op = params.get("operation")
            if op not in TRANSFORMS:
                raise PipelineError(
                    f"Step {i + 1}: unknown transform '{op}'. "
                    f"One of: {', '.join(TRANSFORMS)}")
        if kind == "save_document" and not str(params.get("title", "")).strip():
            raise PipelineError(f"Step {i + 1}: a save step needs a title.")

        cleaned.append({"type": kind, "params": params,
                        "label": step.get("label") or STEP_TYPES[kind]["label"]})
    return cleaned


def catalogue() -> Dict[str, Any]:
    return {
        "steps": [{"type": k, **v} for k, v in STEP_TYPES.items()],
        "transforms": list(TRANSFORMS),
        "max_steps": MAX_STEPS,
    }


# ---------------------------------------------------------------------------
# Storage — pipelines live in settings, so they travel with the project config
# ---------------------------------------------------------------------------
def save_pipeline(project_id: str, name: str,
                  steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise PipelineError("A pipeline needs a name.")
    cleaned = validate(steps)

    from src.settings import get_settings, get_settings_store

    all_pipelines = dict(getattr(get_settings(), "pipelines", None) or {})
    project_pipelines = list(all_pipelines.get(project_id, []))

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60]
    record = {"id": slug, "name": name[:120], "steps": cleaned,
              "updated_at": datetime.utcnow().isoformat()}

    project_pipelines = [p for p in project_pipelines if p.get("id") != slug]
    project_pipelines.append(record)
    all_pipelines[project_id] = project_pipelines
    get_settings_store().update(pipelines=all_pipelines)
    return record


def list_pipelines(project_id: str) -> List[Dict[str, Any]]:
    from src.settings import get_settings

    return list((getattr(get_settings(), "pipelines", None) or {}).get(project_id, []))


def get_pipeline(project_id: str, pipeline_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in list_pipelines(project_id) if p["id"] == pipeline_id), None)


def delete_pipeline(project_id: str, pipeline_id: str) -> bool:
    from src.settings import get_settings, get_settings_store

    all_pipelines = dict(getattr(get_settings(), "pipelines", None) or {})
    current = list(all_pipelines.get(project_id, []))
    remaining = [p for p in current if p.get("id") != pipeline_id]
    if len(remaining) == len(current):
        return False
    all_pipelines[project_id] = remaining
    get_settings_store().update(pipelines=all_pipelines)
    return True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def _apply_transform(text: str, operation: str) -> str:
    if operation == "upper":
        return text.upper()
    if operation == "lower":
        return text.lower()
    if operation == "strip":
        return text.strip()
    if operation == "collapse_blank_lines":
        return re.sub(r"\n{3,}", "\n\n", text)
    if operation == "strip_placeholders":
        return "\n".join(l for l in text.split("\n")
                         if not re.fullmatch(r"\s*[-*+]?\s*(TODO|TBD|FIXME|XXX)\b.*",
                                             l, re.I))
    return text


def _run_verify(text: str, params: Dict[str, Any]) -> Dict[str, Any]:
    failures = []
    min_words = int(params.get("min_words") or 0)
    words = len(text.split())
    if min_words and words < min_words:
        failures.append(f"Too short: {words} words, needs {min_words}.")

    required = params.get("require_sections") or []
    if isinstance(required, str):
        required = [s.strip() for s in required.split(",") if s.strip()]
    headings = {m.group(2).strip().lower()
                for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M)}
    for section in required:
        if section.lower() not in headings:
            failures.append(f"Missing section: {section}")

    if params.get("forbid_placeholders", True):
        for marker in ("TODO", "TBD", "FIXME"):
            if marker.lower() in text.lower():
                failures.append(f"Contains placeholder: {marker}")
                break

    return {"passed": not failures, "failures": failures, "word_count": words}


def _matches_filter(text: str, params: Dict[str, Any]) -> bool:
    lowered = text.lower()
    if params.get("contains") and str(params["contains"]).lower() not in lowered:
        return False
    if params.get("not_contains") and str(params["not_contains"]).lower() in lowered:
        return False
    min_words = int(params.get("min_words") or 0)
    if min_words and len(text.split()) < min_words:
        return False
    return True


async def run(db: DatabaseManager, project_id: str, steps: List[Dict[str, Any]],
              payload: str = "", dry_run: bool = False) -> Dict[str, Any]:
    """Run a pipeline, recording what each step did.

    A failed verify or an unmatched filter *stops* the run rather than raising:
    stopping early is a legitimate outcome, and the trace explains why.
    """
    cleaned = validate(steps)

    with db.get_session() as s:
        if not s.get(Project, project_id):
            raise PipelineError("Project not found.")

    current = payload or ""
    trace: List[Dict[str, Any]] = []
    stopped_at: Optional[int] = None

    for index, step in enumerate(cleaned):
        kind, params = step["type"], step["params"]
        entry: Dict[str, Any] = {"index": index, "type": kind,
                                 "label": step["label"], "ok": True}

        try:
            if kind == "generate":
                prompt = str(params.get("prompt", "")).replace("{{input}}", current)
                if dry_run:
                    entry["detail"] = "dry run — model not called"
                    entry["output_chars"] = 0
                else:
                    from src.services import model_routing

                    current = await model_routing.call(
                        db, "generate", prompt, model=params.get("model", ""),
                        project_id=project_id, max_tokens=1500, temperature=0.4)
                    entry["output_chars"] = len(current)

            elif kind == "transform":
                current = _apply_transform(current, params["operation"])
                entry["detail"] = params["operation"]
                entry["output_chars"] = len(current)

            elif kind == "verify":
                result = _run_verify(current, params)
                entry["passed"] = result["passed"]
                entry["failures"] = result["failures"]
                if not result["passed"]:
                    entry["ok"] = False
                    entry["detail"] = "; ".join(result["failures"][:3])
                    trace.append(entry)
                    stopped_at = index
                    break

            elif kind == "filter":
                if not _matches_filter(current, params):
                    entry["detail"] = "payload did not match — pipeline stopped"
                    trace.append(entry)
                    stopped_at = index
                    break
                entry["detail"] = "matched"

            elif kind == "save_document":
                if dry_run:
                    entry["detail"] = "dry run — nothing written"
                else:
                    node_id = str(uuid.uuid4())
                    with db.get_session() as s:
                        s.add(Node(id=node_id, project_id=project_id,
                                   node_type=params.get("node_type") or "documentation",
                                   title=str(params.get("title"))[:200],
                                   content=current, status="draft"))
                        s.commit()
                    entry["node_id"] = node_id
                    entry["detail"] = f"saved as “{params.get('title')}”"

            elif kind == "capture_idea":
                if dry_run:
                    entry["detail"] = "dry run — nothing captured"
                elif current.strip():
                    from src.services import idea_service

                    idea = idea_service.capture(db, project_id, current[:4000])
                    entry["idea_id"] = idea["id"]
                    entry["detail"] = "captured"
                else:
                    entry["detail"] = "nothing to capture"

        except Exception as e:
            entry["ok"] = False
            entry["detail"] = str(e)[:300]
            trace.append(entry)
            stopped_at = index
            break

        trace.append(entry)

    return {
        "completed": stopped_at is None,
        "stopped_at": stopped_at,
        "steps_run": len(trace),
        "steps_total": len(cleaned),
        "trace": trace,
        "output": current,
        "dry_run": dry_run,
    }


async def run_saved(db: DatabaseManager, project_id: str, pipeline_id: str,
                    payload: str = "", dry_run: bool = False) -> Dict[str, Any]:
    pipeline = get_pipeline(project_id, pipeline_id)
    if not pipeline:
        raise PipelineError("Pipeline not found.")
    out = await run(db, project_id, pipeline["steps"], payload, dry_run)
    out["pipeline"] = {"id": pipeline["id"], "name": pipeline["name"]}
    return out
