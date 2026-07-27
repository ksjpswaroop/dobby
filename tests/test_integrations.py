"""
Webhooks, API keys, and recipes.

The rules that matter: a webhook to a remote host must pass the approval
gate (any path that can create one can also exfiltrate documents), an API
key must be unrecoverable from the database, and a broken webhook must
eventually stop being retried while staying visible.
"""

import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_integ_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.db.integration_models import ApiKey, Webhook  # noqa: E402
from src.main import app  # noqa: E402
from src.services import integration_service as svc  # noqa: E402

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
def auto_approve(monkeypatch):
    async def approve(*a, **k):
        return "approved"

    monkeypatch.setattr("src.services.inbox_service.require", approve)


@pytest.fixture
def auto_deny(monkeypatch):
    async def deny(*a, **k):
        return "denied"

    monkeypatch.setattr("src.services.inbox_service.require", deny)


class TestWebhookApproval:
    @pytest.mark.asyncio
    async def test_remote_host_requires_approval(self, db, auto_deny):
        # Any path that can create a webhook can also exfiltrate documents,
        # so a remote target must be an explicit human decision.
        with pytest.raises(svc.IntegrationError) as e:
            await svc.create_webhook(db, PROJECT, "https://evil.example.com/hook",
                                     ["idea.captured"])
        assert "not approved" in str(e.value)

    @pytest.mark.asyncio
    async def test_approved_remote_host_is_created(self, db, auto_approve):
        hook = await svc.create_webhook(db, PROJECT, "https://ok.example.com/hook",
                                        ["idea.captured"])
        assert hook["url"] == "https://ok.example.com/hook"

    @pytest.mark.asyncio
    async def test_loopback_needs_no_approval(self, db, auto_deny):
        # Never leaves the machine, so the gate would be pure friction.
        hook = await svc.create_webhook(db, PROJECT, "http://127.0.0.1:9000/hook",
                                        ["run.failed"])
        assert hook["id"]

    def test_loopback_detection(self):
        assert svc._is_loopback("http://localhost:3000/x") is True
        assert svc._is_loopback("http://127.0.0.1/x") is True
        assert svc._is_loopback("https://example.com/x") is False


class TestWebhookValidation:
    @pytest.mark.asyncio
    async def test_bad_url_rejected(self, db, auto_approve):
        with pytest.raises(svc.IntegrationError):
            await svc.create_webhook(db, PROJECT, "not-a-url", ["idea.captured"])

    @pytest.mark.asyncio
    async def test_unknown_event_rejected(self, db, auto_approve):
        with pytest.raises(svc.IntegrationError):
            await svc.create_webhook(db, PROJECT, "http://127.0.0.1/x", ["nope"])

    @pytest.mark.asyncio
    async def test_no_events_rejected(self, db, auto_approve):
        with pytest.raises(svc.IntegrationError):
            await svc.create_webhook(db, PROJECT, "http://127.0.0.1/x", [])

    @pytest.mark.asyncio
    async def test_secret_shown_once_at_creation(self, db, auto_approve):
        hook = await svc.create_webhook(db, PROJECT, "http://127.0.0.1/s",
                                        ["idea.captured"])
        assert hook["secret"]
        listed = [h for h in svc.list_webhooks(db, PROJECT) if h["id"] == hook["id"]]
        assert "secret" not in listed[0]


class TestWebhookSigning:
    def test_signature_is_stable_and_secret_dependent(self):
        a = svc.sign_payload("secret1", '{"x":1}')
        b = svc.sign_payload("secret1", '{"x":1}')
        c = svc.sign_payload("secret2", '{"x":1}')
        assert a == b
        assert a != c

    @pytest.mark.asyncio
    async def test_delivery_records_a_failure(self, db, auto_approve):
        hook = await svc.create_webhook(db, PROJECT, "http://127.0.0.1:1/dead",
                                        ["run.failed"])
        out = await svc.fire(db, PROJECT, "run.failed", {"run_id": "x"})
        assert out["failed"] >= 1
        rows = svc.deliveries(db, hook["id"])
        assert rows and rows[0]["ok"] is False

    @pytest.mark.asyncio
    async def test_repeated_failure_disables_the_hook(self, db, auto_approve):
        hook = await svc.create_webhook(db, PROJECT, "http://127.0.0.1:1/dead2",
                                        ["run.failed"])
        for _ in range(svc.MAX_FAILURES_BEFORE_DISABLE):
            await svc.fire(db, PROJECT, "run.failed", {})
        with db.get_session() as s:
            row = s.get(Webhook, hook["id"])
            # Disabled, but the row survives so the user can see why.
            assert row.active == 0
            assert row.failure_count >= svc.MAX_FAILURES_BEFORE_DISABLE

    @pytest.mark.asyncio
    async def test_unknown_event_delivers_nothing(self, db):
        assert (await svc.fire(db, PROJECT, "not.an.event", {}))["delivered"] == 0


class TestApiKeys:
    def test_plaintext_is_returned_once_and_not_stored(self, db):
        out = svc.create_api_key(db, "CI key", ["read"])
        plaintext = out["key"]
        with db.get_session() as s:
            row = s.get(ApiKey, out["id"])
            assert row.key_hash != plaintext
            assert plaintext not in (row.key_hash + row.prefix)
        assert all("key" not in k for k in svc.list_api_keys(db))

    def test_verify_accepts_the_real_key(self, db):
        out = svc.create_api_key(db, "Verify key", ["read"])
        assert svc.verify_api_key(db, out["key"], "read") is not None

    def test_verify_rejects_a_wrong_key(self, db):
        assert svc.verify_api_key(db, "dob_totally_wrong", "read") is None

    def test_scope_is_enforced(self, db):
        out = svc.create_api_key(db, "Read only", ["read"])
        assert svc.verify_api_key(db, out["key"], "read") is not None
        assert svc.verify_api_key(db, out["key"], "write") is None

    def test_admin_scope_implies_others(self, db):
        out = svc.create_api_key(db, "Admin", ["admin"])
        assert svc.verify_api_key(db, out["key"], "write") is not None

    def test_revoked_key_stops_working(self, db):
        out = svc.create_api_key(db, "Revoked", ["read"])
        svc.revoke_api_key(db, out["id"])
        assert svc.verify_api_key(db, out["key"], "read") is None

    def test_use_count_increments(self, db):
        out = svc.create_api_key(db, "Counted", ["read"])
        svc.verify_api_key(db, out["key"], "read")
        svc.verify_api_key(db, out["key"], "read")
        row = next(k for k in svc.list_api_keys(db) if k["id"] == out["id"])
        assert row["use_count"] == 2

    def test_unknown_scope_rejected(self, db):
        with pytest.raises(svc.IntegrationError):
            svc.create_api_key(db, "Bad scope", ["superuser"])

    def test_no_scope_rejected(self, db):
        with pytest.raises(svc.IntegrationError):
            svc.create_api_key(db, "No scope", [])


class TestRecipes:
    def test_condition_free_recipe_always_matches(self):
        assert svc.matches_condition({}, {"anything": 1}) is True

    def test_contains_condition(self):
        assert svc.matches_condition({"contains": "bug"}, {"text": "a BUG report"}) is True
        assert svc.matches_condition({"contains": "bug"}, {"text": "a feature"}) is False

    def test_not_contains_condition(self):
        assert svc.matches_condition({"not_contains": "wip"}, {"text": "done"}) is True
        assert svc.matches_condition({"not_contains": "wip"}, {"text": "WIP thing"}) is False

    def test_field_equals_condition(self):
        assert svc.matches_condition({"field_equals": {"kind": "bug"}},
                                     {"kind": "Bug"}) is True
        assert svc.matches_condition({"field_equals": {"kind": "bug"}},
                                     {"kind": "feature"}) is False

    def test_create_and_list(self, db):
        r = svc.create_recipe(db, PROJECT, "Tag bugs", "idea.captured", "notify",
                              {"message": "a bug was captured"}, {"contains": "bug"})
        assert any(x["id"] == r["id"] for x in svc.list_recipes(db, PROJECT))

    def test_unknown_trigger_rejected(self, db):
        with pytest.raises(svc.IntegrationError):
            svc.create_recipe(db, PROJECT, "Bad", "when.pigs.fly", "notify")

    def test_unknown_action_rejected(self, db):
        with pytest.raises(svc.IntegrationError):
            svc.create_recipe(db, PROJECT, "Bad", "idea.captured", "launch_missiles")

    @pytest.mark.asyncio
    async def test_recipe_fires_only_when_condition_matches(self, db):
        svc.create_recipe(db, PROJECT, "Only bugs", "feature.completed", "notify",
                          {"message": "bug done"}, {"contains": "bug"})
        matched = await svc.run_recipes(db, PROJECT, "feature.completed",
                                        {"title": "fix the bug"})
        missed = await svc.run_recipes(db, PROJECT, "feature.completed",
                                       {"title": "add a chart"})
        assert matched["fired"] >= 1
        assert missed["fired"] == 0

    @pytest.mark.asyncio
    async def test_create_idea_action_works(self, db):
        from src.services import idea_service

        svc.create_recipe(db, PROJECT, "Capture follow-up", "run.failed",
                          "create_idea", {"text": "investigate the failed run"})
        await svc.run_recipes(db, PROJECT, "run.failed", {"run_id": "abc"})
        assert any("investigate the failed run" in i["text"]
                   for i in idea_service.list_ideas(db, PROJECT))

    @pytest.mark.asyncio
    async def test_a_failing_action_does_not_break_the_run(self, db):
        svc.create_recipe(db, PROJECT, "Broken", "run.failed", "tag",
                          {"name": "x"})  # no node_id in payload
        out = await svc.run_recipes(db, PROJECT, "run.failed", {})
        assert out["fired"] >= 1  # evaluated and recorded, not raised

    def test_delete(self, db):
        r = svc.create_recipe(db, PROJECT, "Temp", "idea.captured", "notify")
        assert svc.delete_recipe(db, r["id"]) is True
        assert svc.delete_recipe(db, r["id"]) is False


class TestRoutes:
    def test_meta_lists_vocabulary(self, client):
        body = client.get("/api/v1/integrations/meta").json()
        assert "idea.captured" in body["webhook_events"]
        assert "read" in body["scopes"]

    def test_create_key_via_api_returns_plaintext_once(self, client):
        r = client.post("/api/v1/integrations/keys",
                        json={"name": "API made", "scopes": ["read"]})
        assert r.status_code == 200
        assert r.json()["key"].startswith("dob_")
        assert "only time" in r.json()["warning"]

    def test_bad_scope_400s(self, client):
        r = client.post("/api/v1/integrations/keys",
                        json={"name": "x", "scopes": ["root"]})
        assert r.status_code == 400

    def test_recipes_endpoint(self, client):
        assert client.get(f"/api/v1/integrations/recipes/{PROJECT}").status_code == 200

    def test_webhooks_endpoint(self, client):
        assert client.get(f"/api/v1/integrations/webhooks/{PROJECT}").status_code == 200
