"""
Derive a structured todo-list from a run's event stream (OW row 45).

The roadmap asks for "a progress panel via todo list" — a checklist view,
distinct from the step-by-step log Logs & Traces already shows. Every pipeline
(YOLO, Wizard, Research, the Terminal, Automations) already calls
`Tracer.event()` with its own naming convention (`plan.start`/`plan.done`,
`shell.start`/`shell.done`, `step.start` with a `step=` field, ...) — this
derives the checklist from that existing stream rather than asking every
pipeline to additionally maintain a parallel todo-list data structure, which
would be one more thing to keep in sync and one more way for it to drift.

The heuristic, stated plainly because it is doing real interpretive work:

* A task's identity is its `step` field if one is set (more specific), else
  the event name with any trailing `.start`/`.done`/`.round`/etc. stripped.
* Distinct tasks are ordered by first appearance — that already matches the
  pipeline's real sequence, since events are recorded in the order they happen.
* Status per task comes from the *last* event seen for it, plus the run's
  own final status: an explicit `.done`/`.ok`/`.complete` suffix or `advance`
  step-completion marks a task done outright; a `.failed`/`.error` suffix or
  `level="error"` marks it failed. A task that only ever logged something
  ambiguous (a bare `.start`, a `.round`) is resolved by context — done if the
  run went on to finish successfully (it must have concluded somehow), failed
  if it was the last task before the run failed, in progress if the run is
  still running and it's the most recent task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_DONE_SUFFIXES = {"done", "ok", "complete", "finished"}
_FAILED_SUFFIXES = {"failed", "error"}
_SUFFIX_RE = re.compile(r"\.(?:[a-z]+)$")


@dataclass
class TodoItem:
    key: str
    label: str
    status: str  # pending | in_progress | done | failed
    detail: str = ""
    duration_ms: Optional[int] = None
    first_seen: str = ""
    last_seen: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "detail": self.detail, "duration_ms": self.duration_ms,
            "first_seen": self.first_seen, "last_seen": self.last_seen,
        }


def _task_key(evt: Dict[str, Any]) -> str:
    step = evt.get("step")
    if step:
        return str(step)
    name = str(evt.get("event") or "task")
    return _SUFFIX_RE.sub("", name) or name


def _label(key: str) -> str:
    return key.replace("_", " ").replace(".", " ").strip().capitalize()


def _event_suffix(name: str) -> str:
    m = re.search(r"\.([a-z]+)$", str(name or ""))
    return m.group(1) if m else ""


def derive_todo(run: Dict[str, Any], events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build the checklist. Never raises — malformed events degrade, not crash."""
    order: List[str] = []
    tasks: Dict[str, TodoItem] = {}

    for evt in events:
        try:
            key = _task_key(evt)
        except Exception:
            continue
        if key not in tasks:
            order.append(key)
            tasks[key] = TodoItem(key=key, label=_label(key), status="pending",
                                  first_seen=str(evt.get("ts") or ""))

        item = tasks[key]
        item.last_seen = str(evt.get("ts") or "") or item.last_seen
        if evt.get("message"):
            item.detail = str(evt["message"])[:300]
        if evt.get("duration_ms") is not None:
            item.duration_ms = evt["duration_ms"]

        suffix = _event_suffix(evt.get("event"))
        if evt.get("level") == "error" or suffix in _FAILED_SUFFIXES:
            item.status = "failed"
        elif suffix in _DONE_SUFFIXES:
            item.status = "done"
        elif item.status not in ("done", "failed"):
            item.status = "in_progress"

    run_status = str((run or {}).get("status") or "running")
    for i, key in enumerate(order):
        item = tasks[key]
        if item.status in ("done", "failed"):
            continue  # already unambiguous from its own events
        is_last = i == len(order) - 1
        if not is_last:
            # A later task started, so this ambiguous one must have concluded —
            # true whether the run went on to succeed or fail.
            item.status = "done"
        elif run_status == "ok":
            item.status = "done"
        elif run_status == "failed":
            item.status = "failed"
        # else: run_status == "running" and this is the newest task — leave it
        # as the "in_progress" the event scan already set.

    return [tasks[k].to_dict() for k in order]
