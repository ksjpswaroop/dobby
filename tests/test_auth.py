"""
Per-launch loopback authentication.

The threat this closes is not a remote attacker — it is every other process on
the machine, and every web page the user has open, being able to drive the API
because it happened to bind 127.0.0.1.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_auth_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
from src.security import tokens as T  # noqa: E402


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
def token(client):
    return T.get_token_manager().token


class TestTokenManager:
    def test_publish_writes_an_owner_only_file(self, tmp_path):
        m = T.TokenManager(tmp_path / "runtime.json")
        tok = m.publish(port=1234)
        assert len(tok) > 30
        assert m.path.exists()
        # No group or other permission bits.
        assert (m.path.stat().st_mode & 0o077) == 0

    def test_each_launch_gets_a_different_token(self, tmp_path):
        m = T.TokenManager(tmp_path / "runtime.json")
        assert m.publish() != m.publish()

    def test_verify_rejects_everything_but_the_current_token(self, tmp_path):
        m = T.TokenManager(tmp_path / "runtime.json")
        tok = m.publish()
        assert m.verify(tok) is True
        assert m.verify(tok + "x") is False
        assert m.verify("") is False
        assert m.verify(None) is False

    def test_revoke_removes_the_file_and_invalidates(self, tmp_path):
        m = T.TokenManager(tmp_path / "runtime.json")
        tok = m.publish()
        m.revoke()
        assert not m.path.exists()
        assert m.verify(tok) is False

    def test_an_unwritable_home_does_not_stop_startup(self, tmp_path):
        """A read-only home must degrade, not crash the app."""
        blocked = tmp_path / "nope"
        blocked.write_text("not a directory")
        m = T.TokenManager(blocked / "runtime.json")
        assert m.publish()  # returns a token despite being unable to write

    @pytest.mark.parametrize("header,expected", [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),
        ("Bearer  abc123 ", "abc123"),
        ("Basic abc123", None),
        ("abc123", None),
        ("", None),
        (None, None),
    ])
    def test_bearer_parsing(self, header, expected):
        assert T.bearer_from_header(header) == expected


class TestOriginRules:
    @pytest.mark.parametrize("origin", [
        None,                              # curl / Tauri webview / tests
        "http://localhost:1420",
        "http://localhost:1420/",          # trailing slash tolerated
        "tauri://localhost",
    ])
    def test_first_party_origins_are_trusted(self, origin):
        assert T.origin_is_trusted(origin) is True

    @pytest.mark.parametrize("origin", [
        "http://evil.example", "https://localhost:1420", "http://localhost:9999",
    ])
    def test_other_origins_are_not(self, origin):
        assert T.origin_is_trusted(origin) is False


@pytest.mark.usefixtures("auth_enabled")
class TestGate:
    def test_health_is_reachable_without_a_token(self, client):
        assert client.get("/health").status_code == 200

    def test_an_api_route_without_a_token_is_401(self, client):
        r = client.get("/api/v1/projects")
        assert r.status_code == 401
        # The message must say how to fix it.
        assert "handshake" in r.json()["message"]

    def test_a_wrong_token_is_401(self, client):
        r = client.get("/api/v1/projects",
                       headers={"Authorization": "Bearer not-the-token"})
        assert r.status_code == 401

    def test_the_right_token_is_accepted(self, client, token):
        r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_the_token_also_works_as_a_query_parameter(self, client, token):
        """EventSource cannot set headers, so the stream needs this path."""
        r = client.get(f"/api/v1/projects?token={token}")
        assert r.status_code == 200

    def test_preflight_is_never_blocked(self, client):
        r = client.options("/api/v1/projects", headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
        })
        assert r.status_code < 400

    @pytest.mark.parametrize("path", [
        "/api/v1/mindmaps/types", "/api/v1/research/tracks",
        "/api/v1/automations/meta", "/api/v1/settings",
    ])
    def test_every_subsystem_is_behind_the_gate(self, client, path):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={
            "Authorization": f"Bearer {T.get_token_manager().token}"
        }).status_code == 200


@pytest.mark.usefixtures("auth_enabled")
class TestHandshake:
    def test_a_first_party_caller_gets_the_token(self, client):
        r = client.get("/api/v1/auth/handshake",
                       headers={"Origin": "http://localhost:1420"})
        assert r.status_code == 200
        assert r.json()["token"] == T.get_token_manager().token

    def test_no_origin_is_treated_as_first_party(self, client):
        assert client.get("/api/v1/auth/handshake").status_code == 200

    def test_a_hostile_origin_is_refused(self, client):
        r = client.get("/api/v1/auth/handshake",
                       headers={"Origin": "http://evil.example"})
        assert r.status_code == 403

    def test_the_handshake_token_actually_opens_the_api(self, client):
        tok = client.get("/api/v1/auth/handshake").json()["token"]
        assert client.get("/api/v1/projects",
                          headers={"Authorization": f"Bearer {tok}"}).status_code == 200
