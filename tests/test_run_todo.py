"""
Deriving a todo-list checklist from a run's event stream (OW row 45).

The interesting cases are the ambiguous ones: an event stream that never
explicitly marks a task "done" still has to resolve to a sensible status once
the run's own final state is known.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_todo_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.observability.tracer import Tracer  # noqa: E402
from src.services.run_todo import derive_todo  # noqa: E402

PROJECT = "default-project"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + suffix)
        except OSError:
            pass


@pytest.fixture
def db(client):
    return app.state.db


def ev(event, step=None, level="info", message=""):
    return {"event": event, "step": step, "level": level, "message": message,
            "duration_ms": None, "ts": "2026-07-27T00:00:00"}


class TestDeriveTodo:
    def test_empty_events_is_an_empty_list(self):
        assert derive_todo({"status": "running"}, []) == []

    def test_a_matched_start_done_pair_is_done(self):
        todo = derive_todo({"status": "ok"}, [ev("plan.start"), ev("plan.done")])
        assert len(todo) == 1
        assert todo[0]["key"] == "plan" and todo[0]["status"] == "done"

    def test_an_explicit_failure_is_reported_even_on_a_running_run(self):
        todo = derive_todo({"status": "running"},
                           [ev("plan.start"), ev("plan.failed", level="error")])
        assert todo[0]["status"] == "failed"

    def test_distinct_step_fields_produce_distinct_tasks(self):
        """yolo.py's step.start events all share the event name but differ by step."""
        todo = derive_todo({"status": "ok"}, [
            ev("step.start", step="pseudocode"),
            ev("step.start", step="tdd_tests"),
        ])
        keys = [t["key"] for t in todo]
        assert keys == ["pseudocode", "tdd_tests"]

    def test_order_matches_first_appearance(self):
        todo = derive_todo({"status": "running"},
                           [ev("plan.start"), ev("track.round"), ev("audit.start")])
        assert [t["key"] for t in todo] == ["plan", "track", "audit"]

    def test_an_ambiguous_task_resolves_to_done_when_the_run_succeeded(self):
        """step.start with no matching step.done — the run finishing ok implies
        every task that started must have concluded somehow."""
        todo = derive_todo({"status": "ok"}, [ev("step.start", step="pseudocode")])
        assert todo[0]["status"] == "done"

    def test_the_last_task_is_in_progress_while_the_run_is_still_running(self):
        todo = derive_todo({"status": "running"}, [ev("plan.start"), ev("track.round")])
        assert todo[0]["status"] == "done"          # a later task started, so this concluded
        assert todo[1]["status"] == "in_progress"   # the most recent, run not finished

    def test_the_last_task_becomes_failed_when_the_run_failed(self):
        todo = derive_todo({"status": "failed"}, [ev("plan.start"), ev("track.round")])
        assert todo[0]["status"] == "done"
        assert todo[1]["status"] == "failed"

    def test_a_malformed_event_is_skipped_not_fatal(self):
        assert derive_todo({"status": "running"}, [None, {}, ev("plan.start")]) is not None

    def test_default_status_with_no_run_dict_is_running(self):
        todo = derive_todo(None, [ev("plan.start")])
        assert todo[0]["status"] == "in_progress"

    def test_detail_and_duration_are_carried_from_the_latest_event(self):
        todo = derive_todo({"status": "ok"}, [
            ev("shell.start", message="starting"),
            {**ev("shell.done", message="exit 0"), "duration_ms": 42},
        ])
        assert todo[0]["detail"] == "exit 0"
        assert todo[0]["duration_ms"] == 42


class TestApi:
    def test_todo_endpoint_reflects_a_real_run(self, client, db):
        tracer = Tracer(db, kind="test", label="todo endpoint", project_id=PROJECT,
                        total_steps=2)
        tracer.event("plan.start", "planning")
        tracer.event("plan.done", "planned", advance=True)
        tracer.event("track.start", "tracking")
        tracer.finish("ok")

        r = client.get(f"/api/v1/runs/{tracer.run_id}/todo")
        assert r.status_code == 200
        body = r.json()
        assert body["run"]["status"] == "ok"
        keys = [t["key"] for t in body["todo"]]
        assert keys == ["plan", "track"]
        assert all(t["status"] == "done" for t in body["todo"])

    def test_todo_endpoint_404s_for_a_missing_run(self, client):
        assert client.get("/api/v1/runs/does-not-exist/todo").status_code == 404
