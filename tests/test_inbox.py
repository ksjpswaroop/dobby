"""
Approvals & Inbox.

The rules that matter are the ones that fail *closed*: silence must never
become consent, an expired ask must never be approved, and a grant must never
be broader than what the user actually agreed to.
"""

import asyncio
import os
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_inbox_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.inbox_models import Ask, Grant  # noqa: E402
from src.main import app  # noqa: E402
from src.services import inbox_service as svc  # noqa: E402

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


class TestGrants:
    def test_an_exact_target_matches(self, db):
        svc.grant(db, PROJECT, "net.fetch", "api.github.com")
        assert svc.find_grant(db, PROJECT, "net.fetch", "api.github.com")

    def test_a_different_target_does_not(self, db):
        svc.grant(db, PROJECT, "net.fetch", "safe.example")
        assert svc.find_grant(db, PROJECT, "net.fetch", "evil.example") is None

    def test_a_different_capability_does_not(self, db):
        svc.grant(db, PROJECT, "net.fetch", "shared.example")
        assert svc.find_grant(db, PROJECT, "shell.execute", "shared.example") is None

    def test_a_wildcard_target_matches_its_subdomains(self, db):
        svc.grant(db, PROJECT, "net.fetch", "*.internal.test")
        assert svc.find_grant(db, PROJECT, "net.fetch", "a.internal.test")
        assert svc.find_grant(db, PROJECT, "net.fetch", "other.example") is None

    def test_a_blanket_grant_is_refused(self, db):
        """One careless click must not disable every future check."""
        with pytest.raises(svc.InboxError, match="every target"):
            svc.grant(db, PROJECT, "net.fetch", "*")

    def test_an_unknown_capability_is_refused(self, db):
        with pytest.raises(svc.InboxError, match="Unknown capability"):
            svc.grant(db, PROJECT, "launch.missiles", "somewhere")

    def test_an_expired_grant_does_not_match(self, db):
        g = svc.grant(db, PROJECT, "file.write", "/tmp/expiring", hours=1)
        with db.get_session() as s:
            s.get(Grant, g["id"]).expires_at = datetime.utcnow() - timedelta(minutes=1)
            s.commit()
        assert svc.find_grant(db, PROJECT, "file.write", "/tmp/expiring") is None

    def test_a_revoked_grant_does_not_match(self, db):
        g = svc.grant(db, PROJECT, "file.write", "/tmp/revoked")
        assert svc.revoke_grant(db, g["id"]) is True
        assert svc.find_grant(db, PROJECT, "file.write", "/tmp/revoked") is None

    def test_use_is_counted_so_a_forgotten_grant_is_visible(self, db):
        svc.grant(db, PROJECT, "net.fetch", "counted.example")
        svc.find_grant(db, PROJECT, "net.fetch", "counted.example")
        svc.find_grant(db, PROJECT, "net.fetch", "counted.example")
        g = next(x for x in svc.list_grants(db, PROJECT)
                 if x["target"] == "counted.example")
        assert g["use_count"] == 2


class TestAsks:
    def test_creating_and_answering(self, db):
        a = svc.create_ask(db, PROJECT, "Run a migration?", capability="shell.execute",
                           target="alembic upgrade head")
        assert a["state"] == "pending"
        out = svc.answer_ask(db, a["id"], approved=True, answer="go ahead")
        assert out["state"] == "approved" and out["answer"] == "go ahead"

    def test_answering_twice_is_refused(self, db):
        a = svc.create_ask(db, PROJECT, "Only once")
        svc.answer_ask(db, a["id"], approved=True)
        with pytest.raises(svc.InboxError, match="already"):
            svc.answer_ask(db, a["id"], approved=False)

    def test_denial_never_creates_a_grant(self, db):
        """Remembering a 'no' as a standing 'yes' would be catastrophic."""
        a = svc.create_ask(db, PROJECT, "Nope", capability="net.fetch",
                           target="denied.example")
        svc.answer_ask(db, a["id"], approved=False, remember_hours=24)
        assert svc.find_grant(db, PROJECT, "net.fetch", "denied.example") is None

    def test_approval_can_be_remembered_as_a_grant(self, db):
        a = svc.create_ask(db, PROJECT, "Allow", capability="net.fetch",
                           target="remembered.example")
        out = svc.answer_ask(db, a["id"], approved=True, remember_hours=24)
        assert "grant" in out
        assert svc.find_grant(db, PROJECT, "net.fetch", "remembered.example")

    def test_expiry_marks_expired_not_approved(self, db):
        a = svc.create_ask(db, PROJECT, "Times out", expiry_hours=1)
        with db.get_session() as s:
            s.get(Ask, a["id"]).expires_at = datetime.utcnow() - timedelta(minutes=1)
            s.commit()
        svc.expire_overdue(db)
        assert svc.get_ask(db, a["id"])["state"] == "expired"

    def test_pending_count_tracks_the_badge(self, db):
        before = svc.pending_count(db, PROJECT)
        a = svc.create_ask(db, PROJECT, "Counted")
        assert svc.pending_count(db, PROJECT) == before + 1
        svc.answer_ask(db, a["id"], approved=True)
        assert svc.pending_count(db, PROJECT) == before

    def test_cancel_resolves_without_approving(self, db):
        a = svc.create_ask(db, PROJECT, "Cancel me")
        assert svc.cancel_ask(db, a["id"]) is True
        assert svc.get_ask(db, a["id"])["state"] == "cancelled"

    def test_reconcile_unsticks_asks_stranded_by_a_restart(self, db):
        a = svc.create_ask(db, PROJECT, "Stranded", awaited=True)
        out = svc.reconcile(db, PROJECT)
        assert out["reconnected"] >= 1
        after = svc.get_ask(db, a["id"])
        # Still answerable — just no longer claiming someone is waiting.
        assert after["state"] == "pending" and after["awaited"] is False


class TestRequireGate:
    """The call every consequential action goes through."""

    @pytest.mark.asyncio
    async def test_a_standing_grant_short_circuits_without_asking(self, db):
        svc.grant(db, PROJECT, "net.fetch", "granted.example")
        before = svc.pending_count(db, PROJECT)
        out = await svc.require(db, PROJECT, "net.fetch", "granted.example",
                                "Fetch it")
        assert out["allowed"] is True and out["ask_id"] is None
        assert svc.pending_count(db, PROJECT) == before  # nothing was asked

    @pytest.mark.asyncio
    async def test_an_approval_lets_the_caller_through(self, db):
        async def approve_shortly():
            await asyncio.sleep(0.1)
            pending = svc.list_asks(db, PROJECT, state="pending")
            target = next(a for a in pending if a["title"] == "Needs a yes")
            svc.answer_ask(db, target["id"], approved=True)

        task = asyncio.create_task(approve_shortly())
        out = await svc.require(db, PROJECT, "shell.execute", "ls", "Needs a yes",
                                timeout=5)
        await task
        assert out["allowed"] is True

    @pytest.mark.asyncio
    async def test_a_denial_blocks_the_caller(self, db):
        async def deny_shortly():
            await asyncio.sleep(0.1)
            pending = svc.list_asks(db, PROJECT, state="pending")
            target = next(a for a in pending if a["title"] == "Needs a no")
            svc.answer_ask(db, target["id"], approved=False)

        task = asyncio.create_task(deny_shortly())
        out = await svc.require(db, PROJECT, "shell.execute", "rm -rf /",
                                "Needs a no", timeout=5)
        await task
        assert out["allowed"] is False and out["reason"] == "denied"

    @pytest.mark.asyncio
    async def test_silence_is_not_consent(self, db):
        """The single most important rule in this module."""
        out = await svc.require(db, PROJECT, "shell.execute", "dangerous",
                                "Nobody answers this", timeout=1)
        assert out["allowed"] is False
        assert "timed out" in out["reason"]

    @pytest.mark.asyncio
    async def test_a_timed_out_ask_stays_answerable(self, db):
        """Giving up on waiting must not throw the question away."""
        out = await svc.require(db, PROJECT, "file.write", "/tmp/late",
                                "Answer me later", timeout=1)
        ask = svc.get_ask(db, out["ask_id"])
        assert ask["state"] == "pending" and ask["awaited"] is False
        svc.answer_ask(db, out["ask_id"], approved=True)
        assert svc.get_ask(db, out["ask_id"])["state"] == "approved"


class TestApi:
    def test_meta_lists_capabilities(self, client):
        r = client.get("/api/v1/inbox/meta")
        assert r.status_code == 200
        assert {c["id"] for c in r.json()["capabilities"]} >= {"shell.execute", "net.fetch"}

    def test_create_list_and_answer(self, client):
        r = client.post("/api/v1/inbox/asks", json={
            "project_id": PROJECT, "title": "Via API",
            "capability": "net.fetch", "target": "api.example",
        })
        assert r.status_code == 200, r.text
        ask_id = r.json()["id"]

        listing = client.get(f"/api/v1/inbox/project/{PROJECT}").json()
        assert any(a["id"] == ask_id for a in listing["asks"])
        assert "pending" in listing and "grants" in listing

        r = client.post(f"/api/v1/inbox/asks/{ask_id}/answer",
                        json={"approved": True, "answer": "ok"})
        assert r.status_code == 200 and r.json()["state"] == "approved"

    def test_answering_an_already_answered_ask_is_409(self, client):
        ask_id = client.post("/api/v1/inbox/asks", json={
            "project_id": PROJECT, "title": "Twice",
        }).json()["id"]
        client.post(f"/api/v1/inbox/asks/{ask_id}/answer", json={"approved": True})
        r = client.post(f"/api/v1/inbox/asks/{ask_id}/answer", json={"approved": True})
        assert r.status_code == 409

    def test_a_blanket_grant_is_a_400(self, client):
        r = client.post("/api/v1/inbox/grants", json={
            "project_id": PROJECT, "capability": "net.fetch", "target": "*",
        })
        assert r.status_code == 400 and "every target" in r.json()["detail"]

    def test_grants_can_be_created_and_revoked(self, client):
        gid = client.post("/api/v1/inbox/grants", json={
            "project_id": PROJECT, "capability": "file.write", "target": "/tmp/api",
        }).json()["id"]
        assert client.delete(f"/api/v1/inbox/grants/{gid}").status_code == 200
        assert client.delete(f"/api/v1/inbox/grants/{gid}").status_code == 404

    def test_missing_ask_is_404(self, client):
        assert client.get("/api/v1/inbox/asks/nope").status_code == 404
