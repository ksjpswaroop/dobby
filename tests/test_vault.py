"""
Encryption vault and pipeline builder.

The rules that matter: AES-GCM must reject tampered ciphertext rather than
returning altered bytes, rotation must not strand values under a key nobody
has, and the pipeline builder must never execute anything the user typed.
"""

import base64
import os
import tempfile
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_vault_{uuid.uuid4().hex}.db")
_TMP_META = os.path.join(tempfile.gettempdir(), f"dobby_vaultmeta_{uuid.uuid4().hex}.json")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_VAULT_META"] = _TMP_META
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.services import pipeline_builder as pipes  # noqa: E402
from src.services import vault_service as vault  # noqa: E402

PROJECT = "default-project"
PASSPHRASE = "a long enough passphrase"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    for path in (_TMP_DB, _TMP_DB + "-wal", _TMP_DB + "-shm", _TMP_META):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def db(client):
    return app.state.db


@pytest.fixture
def fresh_vault(monkeypatch):
    """A vault isolated from the real keychain and the user's settings."""
    monkeypatch.setattr(vault, "_memory_keychain", {})
    monkeypatch.setattr(vault, "_keychain_available", lambda: False)
    vault.lock()
    try:
        os.remove(_TMP_META)
    except OSError:
        pass
    yield
    vault.lock()


class TestCrypto:
    def test_round_trip(self):
        key = os.urandom(32)
        blob = vault.encrypt_value("secret value", key)
        assert vault.is_encrypted(blob)
        assert vault.decrypt_value(blob, key) == "secret value"

    def test_ciphertext_hides_the_plaintext(self):
        key = os.urandom(32)
        assert "secret value" not in vault.encrypt_value("secret value", key)

    def test_same_plaintext_encrypts_differently(self):
        # A fresh nonce each time, or identical secrets would be linkable.
        key = os.urandom(32)
        assert vault.encrypt_value("same", key) != vault.encrypt_value("same", key)

    def test_wrong_key_is_rejected(self):
        blob = vault.encrypt_value("secret", os.urandom(32))
        with pytest.raises(vault.VaultError):
            vault.decrypt_value(blob, os.urandom(32))

    def test_tampered_ciphertext_is_rejected(self):
        # GCM authenticates: a flipped bit must fail, not decrypt to garbage.
        key = os.urandom(32)
        blob = vault.encrypt_value("important value", key)
        raw = bytearray(base64.b64decode(blob[len(vault.PREFIX):]))
        raw[-1] ^= 0x01
        tampered = vault.PREFIX + base64.b64encode(bytes(raw)).decode()
        with pytest.raises(vault.VaultError):
            vault.decrypt_value(tampered, key)

    def test_plaintext_passes_through_untouched(self):
        assert vault.decrypt_value("not encrypted", os.urandom(32)) == "not encrypted"

    def test_is_encrypted_detects_the_prefix(self):
        assert vault.is_encrypted("dobbyv1:abc") is True
        assert vault.is_encrypted("plain") is False
        assert vault.is_encrypted(None) is False


class TestLifecycle:
    def test_starts_uninitialised_and_locked(self, fresh_vault):
        s = vault.status()
        assert s["initialised"] is False
        assert s["unlocked"] is False

    def test_initialise_then_locked_by_default_on_relock(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        assert vault.status()["initialised"] is True
        vault.lock()
        # Locking is the default state — a vault that auto-unlocks protects
        # nothing against someone who has the machine.
        assert vault.status()["unlocked"] is False

    def test_short_passphrase_rejected(self, fresh_vault):
        with pytest.raises(vault.VaultError):
            vault.initialise("short")

    def test_double_initialise_rejected(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        with pytest.raises(vault.VaultError):
            vault.initialise("another passphrase entirely")

    def test_unlock_with_the_right_passphrase(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        vault.lock()
        assert vault.unlock(PASSPHRASE)["unlocked"] is True

    def test_unlock_with_a_wrong_passphrase_fails(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        vault.lock()
        with pytest.raises(vault.VaultError):
            vault.unlock("completely wrong passphrase")

    def test_using_a_locked_vault_raises(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        vault.lock()
        with pytest.raises(vault.VaultLocked):
            vault.current_key()

    def test_unlock_before_setup_raises(self, fresh_vault):
        with pytest.raises(vault.VaultError):
            vault.unlock(PASSPHRASE)


class TestSettingsProtection:
    def test_protect_encrypts_and_reveal_decrypts(self, fresh_vault, monkeypatch):
        store = {"tavily_api_key": "tvly-secret-123", "brave_api_key": ""}

        class S:
            def __getattr__(self, name):
                return store.get(name, "")

        class Store:
            def update(self, **changes):
                store.update(changes)

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        monkeypatch.setattr("src.settings.get_settings_store", lambda: Store())

        vault.initialise(PASSPHRASE)
        out = vault.protect_settings()
        assert "tavily_api_key" in out["encrypted"]
        assert vault.is_encrypted(store["tavily_api_key"])
        assert "tvly-secret-123" not in store["tavily_api_key"]
        assert vault.reveal("tavily_api_key") == "tvly-secret-123"

    def test_protect_is_idempotent(self, fresh_vault, monkeypatch):
        store = {"tavily_api_key": "tvly-abc"}

        class S:
            def __getattr__(self, name):
                return store.get(name, "")

        class Store:
            def update(self, **changes):
                store.update(changes)

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        monkeypatch.setattr("src.settings.get_settings_store", lambda: Store())

        vault.initialise(PASSPHRASE)
        vault.protect_settings()
        second = vault.protect_settings()
        assert second["count"] == 0

    def test_reveal_of_an_unprotected_field_rejected(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        with pytest.raises(vault.VaultError):
            vault.reveal("theme")

    def test_rotation_re_encrypts_everything(self, fresh_vault, monkeypatch):
        store = {"tavily_api_key": "rotate-me"}

        class S:
            def __getattr__(self, name):
                return store.get(name, "")

        class Store:
            def update(self, **changes):
                store.update(changes)

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        monkeypatch.setattr("src.settings.get_settings_store", lambda: Store())

        vault.initialise(PASSPHRASE)
        vault.protect_settings()
        before = store["tavily_api_key"]

        vault.rotate(PASSPHRASE, "a brand new passphrase")
        assert store["tavily_api_key"] != before
        # Still readable under the new key — not stranded.
        assert vault.reveal("tavily_api_key") == "rotate-me"

    def test_rotation_with_a_wrong_old_passphrase_rejected(self, fresh_vault):
        vault.initialise(PASSPHRASE)
        with pytest.raises(vault.VaultError):
            vault.rotate("wrong old passphrase", "a brand new passphrase")

    def test_disable_returns_values_to_plaintext(self, fresh_vault, monkeypatch):
        store = {"tavily_api_key": "plain-again"}

        class S:
            def __getattr__(self, name):
                return store.get(name, "")

        class Store:
            def update(self, **changes):
                store.update(changes)

        monkeypatch.setattr("src.settings.get_settings", lambda: S())
        monkeypatch.setattr("src.settings.get_settings_store", lambda: Store())

        vault.initialise(PASSPHRASE)
        vault.protect_settings()
        vault.disable(PASSPHRASE)
        assert store["tavily_api_key"] == "plain-again"
        assert vault.status()["initialised"] is False


class TestPipelineValidation:
    def test_unknown_step_type_rejected(self):
        # The builder must never accept anything resembling executable input.
        with pytest.raises(pipes.PipelineError):
            pipes.validate([{"type": "exec_shell", "params": {"cmd": "rm -rf /"}}])

    def test_empty_pipeline_rejected(self):
        with pytest.raises(pipes.PipelineError):
            pipes.validate([])

    def test_too_many_steps_rejected(self):
        with pytest.raises(pipes.PipelineError):
            pipes.validate([{"type": "transform", "params": {"operation": "strip"}}]
                           * (pipes.MAX_STEPS + 1))

    def test_generate_without_a_prompt_rejected(self):
        with pytest.raises(pipes.PipelineError):
            pipes.validate([{"type": "generate", "params": {}}])

    def test_unknown_transform_rejected(self):
        with pytest.raises(pipes.PipelineError):
            pipes.validate([{"type": "transform", "params": {"operation": "explode"}}])

    def test_save_without_a_title_rejected(self):
        with pytest.raises(pipes.PipelineError):
            pipes.validate([{"type": "save_document", "params": {}}])

    def test_valid_pipeline_passes(self):
        out = pipes.validate([
            {"type": "transform", "params": {"operation": "strip"}},
            {"type": "verify", "params": {"min_words": 1}},
        ])
        assert len(out) == 2

    def test_catalogue_lists_steps(self):
        cat = pipes.catalogue()
        assert any(s["type"] == "generate" for s in cat["steps"])
        assert "strip" in cat["transforms"]


class TestPipelineExecution:
    @pytest.mark.asyncio
    async def test_transform_chain(self, db):
        out = await pipes.run(db, PROJECT, [
            {"type": "transform", "params": {"operation": "strip"}},
            {"type": "transform", "params": {"operation": "upper"}},
        ], payload="  hello  ")
        assert out["completed"] is True
        assert out["output"] == "HELLO"

    @pytest.mark.asyncio
    async def test_failed_verify_stops_the_run(self, db):
        out = await pipes.run(db, PROJECT, [
            {"type": "verify", "params": {"min_words": 100}},
            {"type": "transform", "params": {"operation": "upper"}},
        ], payload="too short")
        assert out["completed"] is False
        assert out["stopped_at"] == 0
        assert out["steps_run"] == 1
        assert out["trace"][0]["failures"]

    @pytest.mark.asyncio
    async def test_unmatched_filter_stops_the_run(self, db):
        out = await pipes.run(db, PROJECT, [
            {"type": "filter", "params": {"contains": "banana"}},
            {"type": "transform", "params": {"operation": "upper"}},
        ], payload="no fruit here")
        assert out["completed"] is False
        assert "did not match" in out["trace"][0]["detail"]

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, db):
        from src.db.schema import Node

        with db.get_session() as s:
            before = s.query(Node).filter(Node.project_id == PROJECT).count()
        out = await pipes.run(db, PROJECT, [
            {"type": "save_document", "params": {"title": "Dry run doc"}},
        ], payload="body", dry_run=True)
        with db.get_session() as s:
            assert s.query(Node).filter(Node.project_id == PROJECT).count() == before
        assert out["completed"] is True

    @pytest.mark.asyncio
    async def test_save_document_writes_a_real_node(self, db):
        from src.db.schema import Node

        out = await pipes.run(db, PROJECT, [
            {"type": "save_document", "params": {"title": "Pipeline output"}},
        ], payload="# Result\n\nGenerated by a pipeline.")
        node_id = out["trace"][0]["node_id"]
        with db.get_session() as s:
            assert s.get(Node, node_id).title == "Pipeline output"

    @pytest.mark.asyncio
    async def test_capture_idea_step(self, db):
        from src.services import idea_service

        await pipes.run(db, PROJECT, [{"type": "capture_idea", "params": {}}],
                        payload="an idea from a pipeline")
        assert any("an idea from a pipeline" in i["text"]
                   for i in idea_service.list_ideas(db, PROJECT))

    @pytest.mark.asyncio
    async def test_generate_step_uses_the_model(self, db, monkeypatch):
        async def fake_call(*a, **k):
            return "model output"

        monkeypatch.setattr("src.services.model_routing.call", fake_call)
        out = await pipes.run(db, PROJECT, [
            {"type": "generate", "params": {"prompt": "Write about {{input}}"}},
        ], payload="testing")
        assert out["output"] == "model output"

    @pytest.mark.asyncio
    async def test_a_step_error_stops_and_is_recorded(self, db, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("model exploded")

        monkeypatch.setattr("src.services.model_routing.call", boom)
        out = await pipes.run(db, PROJECT, [
            {"type": "generate", "params": {"prompt": "x"}},
            {"type": "transform", "params": {"operation": "upper"}},
        ])
        assert out["completed"] is False
        assert out["trace"][0]["ok"] is False
        assert "exploded" in out["trace"][0]["detail"]


class TestRoutes:
    def test_vault_status_endpoint(self, client):
        assert client.get("/api/v1/vault/status").status_code == 200

    def test_catalogue_endpoint(self, client):
        body = client.get("/api/v1/pipelines/catalogue").json()
        assert any(s["type"] == "verify" for s in body["steps"])

    def test_invalid_pipeline_400s(self, client):
        r = client.post("/api/v1/pipelines/validate", json={
            "project_id": PROJECT, "name": "bad",
            "steps": [{"type": "exec_shell", "params": {}}]})
        assert r.status_code == 400

    def test_run_endpoint(self, client):
        r = client.post("/api/v1/pipelines/run", json={
            "project_id": PROJECT,
            "steps": [{"type": "transform", "params": {"operation": "upper"}}],
            "payload": "abc"})
        assert r.status_code == 200
        assert r.json()["output"] == "ABC"

    def test_unlock_with_bad_passphrase_401s(self, client):
        r = client.post("/api/v1/vault/unlock", json={"passphrase": "nope nope nope"})
        assert r.status_code == 401
