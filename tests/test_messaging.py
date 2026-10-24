"""
Messaging connectors.

A webhook endpoint is a URL anyone can POST to, so the signature check is the
whole security boundary and is tested with real HMAC computation rather than a
stub. The other rule that matters is that nothing is ever silently dropped:
what cannot be routed is dead-lettered with a reason.
"""

import hashlib
import hmac
import json
import os
import tempfile
import time
import uuid

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), f"dobby_msg_{uuid.uuid4().hex}.db")
os.environ["DOBBY_DB_PATH"] = _TMP_DB
os.environ["DOBBY_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from src.connectors.base import (  # noqa: E402
    ConnectorError, Message, SlackConnector, TelegramConnector, build,
)
from src.main import app  # noqa: E402
from src.services import messaging_service as svc  # noqa: E402

PROJECT = "default-project"
SECRET = "s3cr3t-signing-key"
BOT = "xoxb-fake-token"


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


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "CONFIG_PATH", tmp_path / "connectors.json")
    monkeypatch.setattr(svc, "DEAD_LETTER_PATH", tmp_path / "dead.json")
    svc._recent.clear()
    yield


def slack_headers(body: bytes, secret: str = SECRET,
                  timestamp: str = "") -> dict:
    """A genuine Slack v0 signature."""
    ts = timestamp or str(int(time.time()))
    base = b"v0:" + ts.encode() + b":" + body
    sig = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return {"x-slack-request-timestamp": ts, "x-slack-signature": sig}


class TestSlackSignature:
    def setup_method(self):
        self.c = SlackConnector({"bot_token": BOT, "signing_secret": SECRET})

    def test_a_correct_signature_verifies(self):
        body = b'{"hello":"world"}'
        assert self.c.verify(body, slack_headers(body)) is True

    def test_a_tampered_body_fails(self):
        body = b'{"hello":"world"}'
        headers = slack_headers(body)
        assert self.c.verify(b'{"hello":"evil"}', headers) is False

    def test_a_wrong_secret_fails(self):
        body = b"{}"
        assert self.c.verify(body, slack_headers(body, secret="wrong")) is False

    def test_an_old_timestamp_is_refused(self):
        """A validly-signed request must not replay forever."""
        body = b"{}"
        old = str(int(time.time()) - 3600)
        assert self.c.verify(body, slack_headers(body, timestamp=old)) is False

    @pytest.mark.parametrize("headers", [
        {}, {"x-slack-signature": "v0=abc"}, {"x-slack-request-timestamp": "123"},
    ])
    def test_missing_headers_fail(self, headers):
        assert self.c.verify(b"{}", headers) is False

    def test_a_non_numeric_timestamp_fails(self):
        assert self.c.verify(b"{}", {"x-slack-request-timestamp": "soon",
                                     "x-slack-signature": "v0=x"}) is False

    def test_an_unconfigured_connector_verifies_nothing(self):
        body = b"{}"
        assert SlackConnector({}).verify(body, slack_headers(body)) is False


class TestTelegramSignature:
    def test_a_matching_secret_verifies(self):
        c = TelegramConnector({"bot_token": BOT, "webhook_secret": "abc"})
        assert c.verify(b"{}", {"x-telegram-bot-api-secret-token": "abc"}) is True

    def test_a_wrong_secret_fails(self):
        c = TelegramConnector({"bot_token": BOT, "webhook_secret": "abc"})
        assert c.verify(b"{}", {"x-telegram-bot-api-secret-token": "xyz"}) is False

    def test_no_configured_secret_means_nothing_is_authentic(self):
        """An unauthenticated webhook must not be treated as verified."""
        c = TelegramConnector({"bot_token": BOT})
        assert c.verify(b"{}", {"x-telegram-bot-api-secret-token": ""}) is False


class TestSlackParsing:
    def setup_method(self):
        self.c = SlackConnector({"bot_token": BOT, "signing_secret": SECRET,
                                 "bot_user_id": "U0BOT"})

    def test_a_mention_is_recognised(self):
        m = self.c.parse({"event": {"type": "app_mention", "channel": "C1",
                                    "user": "U1", "text": "<@U0BOT> hello",
                                    "ts": "1.0"}})
        assert m.mentioned is True and m.channel == "C1"

    def test_a_dm_is_recognised_by_channel_prefix(self):
        m = self.c.parse({"event": {"type": "message", "channel": "D9",
                                    "user": "U1", "text": "hi", "ts": "1.0"}})
        assert m.is_direct is True

    def test_our_own_messages_are_ignored(self):
        """Echoing a bot's output back into it is how you build a loop."""
        assert self.c.parse({"event": {"type": "message", "bot_id": "B1",
                                       "channel": "C1", "text": "mine"}}) is None

    def test_edits_and_joins_are_ignored(self):
        assert self.c.parse({"event": {"type": "message", "subtype": "message_changed",
                                       "channel": "C1", "text": "x"}}) is None

    def test_non_message_events_are_ignored(self):
        assert self.c.parse({"event": {"type": "reaction_added"}}) is None

    def test_a_plain_channel_message_is_not_a_mention(self):
        m = self.c.parse({"event": {"type": "message", "channel": "C1",
                                    "user": "U1", "text": "no mention", "ts": "1.0"}})
        assert m.mentioned is False and m.is_direct is False


class TestTelegramParsing:
    def setup_method(self):
        self.c = TelegramConnector({"bot_token": BOT, "bot_username": "dobbybot"})

    def test_a_private_chat_is_direct_and_addressed(self):
        m = self.c.parse({"message": {"text": "hi", "chat": {"id": 5, "type": "private"},
                                      "from": {"username": "sam"}}})
        assert m.is_direct is True and m.mentioned is True

    def test_a_group_mention_is_recognised(self):
        m = self.c.parse({"message": {"text": "@dobbybot help",
                                      "chat": {"id": -100, "type": "group"},
                                      "from": {"username": "sam"}}})
        assert m.mentioned is True and m.is_direct is False

    def test_a_message_without_text_is_ignored(self):
        assert self.c.parse({"message": {"chat": {"id": 1}}}) is None


class TestRouting:
    @pytest.mark.parametrize("kwargs,expected", [
        ({"mentioned": True}, True),
        ({"is_direct": True}, True),
        ({}, False),
    ])
    def test_addressed_messages_are_handled(self, kwargs, expected):
        m = Message("slack", "C1", "U1", "hi", **kwargs)
        assert svc.should_handle(m, [])[0] is expected

    def test_a_subscribed_channel_is_handled(self):
        m = Message("slack", "C-watched", "U1", "hi")
        assert svc.should_handle(m, ["C-watched"])[0] is True

    def test_the_reason_is_always_given(self):
        m = Message("slack", "C1", "U1", "hi")
        handled, reason = svc.should_handle(m, [])
        assert handled is False and "not mentioned" in reason


class TestDeadLetters:
    def test_an_unrouted_message_is_kept_with_its_reason(self):
        """Silently dropping is what makes a chat integration untrustworthy."""
        svc.dead_letter(Message("slack", "C1", "U1", "ignored"), "not subscribed")
        rows = svc.dead_letters()
        assert rows and rows[0]["reason"] == "not subscribed"
        assert rows[0]["message"]["text"] == "ignored"

    def test_the_store_is_capped(self, monkeypatch):
        monkeypatch.setattr(svc, "MAX_DEAD_LETTERS", 5)
        for i in range(12):
            svc.dead_letter(Message("slack", "C", "U", f"m{i}"), "test")
        assert len(svc.dead_letters()) == 5

    def test_clearing_reports_how_many_went(self):
        svc.dead_letter(Message("slack", "C", "U", "x"), "test")
        assert svc.clear_dead_letters() >= 1
        assert svc.dead_letters() == []


class TestConfiguration:
    def test_configure_and_status(self):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        st = svc.status("slack")
        assert st["configured"] is True and st["missing"] == []

    def test_credentials_are_never_echoed_back(self):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        assert BOT not in json.dumps(svc.status())

    def test_partial_configuration_names_what_is_missing(self):
        svc.configure("slack", {"bot_token": BOT})
        st = svc.status("slack")
        assert st["configured"] is False and "signing_secret" in st["missing"]

    def test_configuring_merges_rather_than_replaces(self):
        svc.configure("slack", {"bot_token": BOT})
        svc.configure("slack", {"signing_secret": SECRET})
        assert svc.status("slack")["configured"] is True

    def test_subscriptions_round_trip(self):
        svc.subscribe("slack", "C-alpha")
        svc.subscribe("slack", "C-beta")
        assert svc.subscriptions("slack") == ["C-alpha", "C-beta"]
        svc.unsubscribe("slack", "C-alpha")
        assert svc.subscriptions("slack") == ["C-beta"]

    def test_an_unknown_connector_is_refused(self):
        with pytest.raises(svc.MessagingError, match="Unknown connector"):
            svc.configure("carrier-pigeon", {})
        with pytest.raises(ConnectorError, match="Unknown connector"):
            build("smoke-signals")


class TestWebhook:
    @pytest.mark.asyncio
    async def test_an_unsigned_request_is_rejected(self, db):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        with pytest.raises(svc.MessagingError, match="Signature"):
            await svc.handle_webhook(db, PROJECT, "slack", b"{}", {}, {})

    @pytest.mark.asyncio
    async def test_an_unverified_payload_is_not_stored(self, db):
        """An unauthenticated request is a stranger, not a message."""
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        before = len(svc.dead_letters())
        with pytest.raises(svc.MessagingError):
            await svc.handle_webhook(db, PROJECT, "slack", b'{"evil":1}',
                                     {"x-slack-signature": "v0=nope",
                                      "x-slack-request-timestamp": str(int(time.time()))},
                                     {"evil": 1})
        assert len(svc.dead_letters()) == before

    @pytest.mark.asyncio
    async def test_the_url_verification_handshake(self, db):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        payload = {"type": "url_verification", "challenge": "abc123"}
        body = json.dumps(payload).encode()
        out = await svc.handle_webhook(db, PROJECT, "slack", body,
                                       slack_headers(body), payload)
        assert out["challenge"] == "abc123"

    @pytest.mark.asyncio
    async def test_a_mention_is_handled(self, db):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET,
                                "bot_user_id": "U0BOT"})
        payload = {"event": {"type": "app_mention", "channel": "C1", "user": "U1",
                             "text": "<@U0BOT> status?", "ts": "1.0"}}
        body = json.dumps(payload).encode()
        out = await svc.handle_webhook(db, PROJECT, "slack", body,
                                       slack_headers(body), payload)
        assert out["handled"] is True and out["reason"] == "mentioned"

    @pytest.mark.asyncio
    async def test_an_unrouted_message_is_dead_lettered(self, db):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        payload = {"event": {"type": "message", "channel": "C-other", "user": "U1",
                             "text": "chatter", "ts": "1.0"}}
        body = json.dumps(payload).encode()
        out = await svc.handle_webhook(db, PROJECT, "slack", body,
                                       slack_headers(body), payload)
        assert out["handled"] is False
        assert any(r["message"]["text"] == "chatter" for r in svc.dead_letters())

    @pytest.mark.asyncio
    async def test_messages_enter_the_recent_buffer(self, db):
        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        payload = {"event": {"type": "message", "channel": "C-x", "user": "U1",
                             "text": "buffered", "ts": "1.0"}}
        body = json.dumps(payload).encode()
        await svc.handle_webhook(db, PROJECT, "slack", body,
                                 slack_headers(body), payload)
        assert any(m["text"] == "buffered" for m in svc.recent("slack"))


class TestOutbound:
    @pytest.mark.asyncio
    async def test_a_new_message_requires_approval(self, db, monkeypatch):
        from src.services import inbox_service as inbox

        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})

        async def deny(*a, **k):
            return {"allowed": False, "reason": "denied", "ask_id": "x"}

        monkeypatch.setattr(inbox, "require", deny)
        out = await svc.reply(db, PROJECT, "slack", "C1", "unsolicited")
        assert out["sent"] is False

    @pytest.mark.asyncio
    async def test_replying_where_addressed_is_pre_approved(self, db, monkeypatch):
        """OW 34 — asking permission to answer a direct question would make
        the integration unusable, and intent is already clear."""
        from src.services import inbox_service as inbox

        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})
        asked = {"n": 0}

        async def counting(*a, **k):
            asked["n"] += 1
            return {"allowed": False, "reason": "denied"}

        monkeypatch.setattr(inbox, "require", counting)

        sent = {}

        async def fake_send(self, channel, text, thread=None):
            sent.update({"channel": channel, "text": text})
            return {"ts": "1.0"}

        monkeypatch.setattr(SlackConnector, "send", fake_send)

        incoming = Message("slack", "C1", "U1", "hi", mentioned=True)
        out = await svc.reply(db, PROJECT, "slack", "C1", "answer",
                              in_reply_to=incoming)
        assert out["sent"] is True and out["pre_approved"] is True
        assert asked["n"] == 0

    @pytest.mark.asyncio
    async def test_pre_approval_does_not_extend_to_another_channel(self, db, monkeypatch):
        from src.services import inbox_service as inbox

        svc.configure("slack", {"bot_token": BOT, "signing_secret": SECRET})

        async def deny(*a, **k):
            return {"allowed": False, "reason": "denied"}

        monkeypatch.setattr(inbox, "require", deny)
        incoming = Message("slack", "C1", "U1", "hi", mentioned=True)
        out = await svc.reply(db, PROJECT, "slack", "C-DIFFERENT", "sneaky",
                              in_reply_to=incoming)
        assert out["sent"] is False

    @pytest.mark.asyncio
    async def test_sending_without_configuration_is_refused(self, db):
        with pytest.raises(svc.MessagingError, match="not configured"):
            await svc.reply(db, PROJECT, "slack", "C1", "hi")


class TestApi:
    def test_status_reports_both_connectors(self, client):
        r = client.get("/api/v1/messaging/status")
        assert r.status_code == 200
        assert {"slack", "telegram"} <= set(r.json()["connectors"])

    def test_configure_and_subscribe_over_http(self, client):
        assert client.put("/api/v1/messaging/slack/configure", json={
            "credentials": {"bot_token": BOT, "signing_secret": SECRET},
        }).status_code == 200
        r = client.post("/api/v1/messaging/slack/subscriptions",
                        json={"channel": "C-api"})
        assert "C-api" in r.json()["subscriptions"]

    def test_an_unsigned_webhook_is_401(self, client):
        client.put("/api/v1/messaging/slack/configure", json={
            "credentials": {"bot_token": BOT, "signing_secret": SECRET},
        })
        r = client.post("/api/v1/messaging/slack/webhook", json={"event": {}})
        assert r.status_code == 401

    def test_the_webhook_is_reachable_without_a_launch_token(self):
        """Slack cannot hold one — it authenticates by signature instead."""
        from src.security.tokens import is_open_path

        assert is_open_path("/api/v1/messaging/slack/webhook") is True
        assert is_open_path("/api/v1/messaging/status") is False

    def test_dead_letters_are_readable(self, client):
        assert client.get("/api/v1/messaging/dead-letters").status_code == 200
