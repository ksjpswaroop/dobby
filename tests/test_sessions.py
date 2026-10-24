"""
Durable sessions and permission modes.

The tests that matter are about the *gate*. A permission mode is a promise
about what can happen while you are not watching, and the two ways to break
that promise are letting `readonly` be defeated by a standing grant, and letting
`unattended` quietly mean `unsupervised`.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_sess_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.session_models import WorkSession  # noqa: E402
from src.main import app  # noqa: E402
from src.services import inbox_service as inbox  # noqa: E402
from src.services import session_service as svc  # noqa: E402

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


@pytest.fixture
def session(db):
    return svc.create(db, PROJECT, "Test session")


class TestLifecycle:
    def test_a_new_session_is_active_and_asks_by_default(self, db):
        s = svc.create(db, PROJECT, "Fresh")
        assert s["state"] == "active" and s["permission_mode"] == "ask"

    def test_an_invalid_mode_is_refused(self, db):
        with pytest.raises(svc.SessionError, match="Permission mode"):
            svc.create(db, PROJECT, "Bad", permission_mode="yolo")

    def test_an_empty_title_is_refused(self, db):
        with pytest.raises(svc.SessionError, match="title"):
            svc.create(db, PROJECT, "   ")

    def test_suspend_and_resume(self, db, session):
        assert svc.suspend(db, session["id"])["state"] == "suspended"
        assert svc.resume(db, session["id"])["state"] == "active"

    def test_resuming_an_active_session_is_a_no_op(self, db, session):
        assert svc.resume(db, session["id"])["state"] == "active"

    def test_a_finished_session_cannot_be_resumed(self, db, session):
        svc.finish(db, session["id"], ok=True)
        with pytest.raises(svc.SessionError, match="cannot be resumed"):
            svc.resume(db, session["id"])

    def test_suspending_a_suspended_session_is_refused(self, db, session):
        svc.suspend(db, session["id"])
        with pytest.raises(svc.SessionError, match="Only an active session"):
            svc.suspend(db, session["id"])

    def test_the_timeline_records_what_happened(self, db, session):
        svc.suspend(db, session["id"])
        svc.resume(db, session["id"])
        kinds = [e["event"] for e in svc.events(db, session["id"])]
        assert {"started", "suspended", "resumed"} <= set(kinds)


class TestCheckpoint:
    def test_state_is_merged_not_replaced(self, db, session):
        svc.checkpoint(db, session["id"], {"step": 1, "topic": "x"})
        out = svc.checkpoint(db, session["id"], {"step": 2})
        assert out["checkpoint"] == {"step": 2, "topic": "x"}

    def test_the_revision_counter_advances(self, db, session):
        first = svc.checkpoint(db, session["id"], {"a": 1})["revision"]
        second = svc.checkpoint(db, session["id"], {"a": 2})["revision"]
        assert second == first + 1

    def test_a_checkpoint_survives_a_reload(self, db, session):
        svc.checkpoint(db, session["id"], {"resume_from": "track-3"})
        assert svc.get(db, session["id"])["checkpoint"]["resume_from"] == "track-3"

    def test_a_finished_session_rejects_checkpoints(self, db, session):
        svc.finish(db, session["id"])
        with pytest.raises(svc.SessionError, match="cannot be updated"):
            svc.checkpoint(db, session["id"], {"late": True})


class TestReconcile:
    def test_a_restart_suspends_rather_than_fails(self, db):
        """Failing them would discard checkpoints that are still good."""
        a = svc.create(db, PROJECT, "Was running")
        out = svc.reconcile(db, PROJECT)
        assert out["suspended"] >= 1
        after = svc.get(db, a["id"])
        assert after["state"] == "suspended"
        assert "restart" in (after["note"] or "").lower()
        # And it is immediately resumable, with its checkpoint intact.
        assert svc.resume(db, a["id"])["state"] == "active"


class TestGate:
    @pytest.mark.asyncio
    async def test_no_session_behaves_exactly_like_the_inbox(self, db, monkeypatch):
        async def approve(*a, **k):
            return {"allowed": True, "reason": "approved", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", approve)
        out = await svc.gate(db, None, PROJECT, "net.fetch", "x", "t")
        assert out["allowed"] is True and out["mode"] == "ask"

    @pytest.mark.asyncio
    async def test_readonly_refuses_every_write_capability(self, db):
        s = svc.create(db, PROJECT, "Read only", permission_mode="readonly")
        for capability in ("shell.execute", "file.write", "message.send",
                           "net.fetch", "automation.run"):
            out = await svc.gate(db, s["id"], PROJECT, capability, "t", "title")
            assert out["allowed"] is False
            assert out["reason"] == "this session is read-only"

    @pytest.mark.asyncio
    async def test_readonly_cannot_be_defeated_by_a_standing_grant(self, db):
        """A mode a grant could quietly override would be a setting that lies."""
        inbox.grant(db, PROJECT, "shell.execute", "ls")
        s = svc.create(db, PROJECT, "Locked down", permission_mode="readonly")
        out = await svc.gate(db, s["id"], PROJECT, "shell.execute", "ls", "run ls")
        assert out["allowed"] is False

    @pytest.mark.asyncio
    async def test_unattended_auto_approves_only_low_risk(self, db, monkeypatch):
        asked = {"count": 0}

        async def counting(*a, **k):
            asked["count"] += 1
            return {"allowed": False, "reason": "denied", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", counting)
        s = svc.create(db, PROJECT, "Overnight", permission_mode="unattended")

        low = await svc.gate(db, s["id"], PROJECT, "net.fetch", "t", "x", risk="low")
        assert low["allowed"] is True and asked["count"] == 0

        # Medium and high must still reach the Inbox — otherwise "unattended"
        # silently means "unsupervised".
        await svc.gate(db, s["id"], PROJECT, "shell.execute", "t", "x", risk="medium")
        await svc.gate(db, s["id"], PROJECT, "shell.execute", "t", "x", risk="high")
        assert asked["count"] == 2

    @pytest.mark.asyncio
    async def test_an_auto_approval_is_recorded(self, db):
        s = svc.create(db, PROJECT, "Audited", permission_mode="unattended")
        await svc.gate(db, s["id"], PROJECT, "net.fetch", "t", "x", risk="low")
        assert any(e["event"] == "auto_approved" for e in svc.events(db, s["id"]))

    @pytest.mark.asyncio
    async def test_a_suspended_session_permits_nothing(self, db):
        s = svc.create(db, PROJECT, "Asleep")
        svc.suspend(db, s["id"])
        out = await svc.gate(db, s["id"], PROJECT, "net.fetch", "t", "x", risk="low")
        assert out["allowed"] is False and "suspended" in out["reason"]

    @pytest.mark.asyncio
    async def test_changing_mode_changes_behaviour_immediately(self, db):
        s = svc.create(db, PROJECT, "Switcher", permission_mode="readonly")
        blocked = await svc.gate(db, s["id"], PROJECT, "net.fetch", "t", "x", risk="low")
        assert blocked["allowed"] is False

        svc.set_mode(db, s["id"], "unattended")
        allowed = await svc.gate(db, s["id"], PROJECT, "net.fetch", "t", "x", risk="low")
        assert allowed["allowed"] is True


class TestApi:
    def test_meta_lists_the_modes(self, client):
        r = client.get("/api/v1/sessions/meta")
        assert r.status_code == 200
        assert {m["id"] for m in r.json()["modes"]} == {"ask", "unattended", "readonly"}

    def test_full_lifecycle_over_http(self, client):
        r = client.post("/api/v1/sessions", json={
            "project_id": PROJECT, "title": "API session",
            "permission_mode": "unattended",
        })
        assert r.status_code == 200, r.text
        sid = r.json()["id"]

        assert client.put(f"/api/v1/sessions/{sid}/checkpoint",
                          json={"state": {"step": 4}}).json()["checkpoint"]["step"] == 4
        assert client.post(f"/api/v1/sessions/{sid}/suspend").json()["state"] == "suspended"
        assert client.post(f"/api/v1/sessions/{sid}/resume").json()["state"] == "active"
        assert client.put(f"/api/v1/sessions/{sid}/mode",
                          json={"permission_mode": "readonly"}
                          ).json()["permission_mode"] == "readonly"
        assert client.post(f"/api/v1/sessions/{sid}/finish",
                           json={"ok": True}).json()["state"] == "completed"
        assert client.get(f"/api/v1/sessions/{sid}/events").json()["events"]

    def test_an_invalid_mode_is_a_400(self, client):
        sid = client.post("/api/v1/sessions", json={
            "project_id": PROJECT, "title": "Mode test",
        }).json()["id"]
        r = client.put(f"/api/v1/sessions/{sid}/mode", json={"permission_mode": "nope"})
        assert r.status_code == 400

    def test_missing_session_is_404(self, client):
        assert client.get("/api/v1/sessions/nope").status_code == 404
        assert client.post("/api/v1/sessions/nope/suspend").status_code == 404
