"""
Messaging connectors (OW rows 18, 33-39 — Next Task 10).

One transport interface, so Slack and Telegram differ only where they actually
differ. A connector does four things:

* **receive** — normalise an inbound payload into a `Message`.
* **send** — post a reply, optionally in a thread.
* **subscribe** — declare which channels are watched.
* **verify** — confirm a webhook really came from the provider.

`verify` is not optional. A webhook endpoint is a URL anyone can POST to, and a
connector that trusts its input lets a stranger drive the app. Slack signs every
request; Telegram uses a secret token header. Both are checked before the
payload is looked at.

The **dead-letter store** (OW 38) exists because messages arrive for
conversations that no longer exist, from users who are not routed anywhere, or
while the app is mid-restart. Dropping them silently is the failure mode that
makes a chat integration untrustworthy — you can never tell whether nothing
happened because nothing was said.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# A Slack signature older than this is refused: a replayed request must not work
# indefinitely just because it was validly signed once.
SIGNATURE_MAX_AGE = 60 * 5


@dataclass
class Message:
    """A normalised inbound message, whatever the transport."""

    connector: str
    channel: str
    user: str
    text: str
    thread: Optional[str] = None
    mentioned: bool = False
    is_direct: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connector": self.connector, "channel": self.channel,
            "user": self.user, "text": self.text, "thread": self.thread,
            "mentioned": self.mentioned, "is_direct": self.is_direct,
            "received_at": self.received_at.isoformat(),
        }


class ConnectorError(Exception):
    """Message is user-facing."""


class Connector:
    """A messaging transport."""

    name = "base"
    # What the user must supply before this can work at all.
    required_credentials: List[str] = []

    def __init__(self, config: Optional[Dict[str, str]] = None):
        self.config = config or {}

    @property
    def configured(self) -> bool:
        return all(self.config.get(k) for k in self.required_credentials)

    def missing_credentials(self) -> List[str]:
        return [k for k in self.required_credentials if not self.config.get(k)]

    def verify(self, body: bytes, headers: Dict[str, str]) -> bool:
        raise NotImplementedError

    def parse(self, payload: Dict[str, Any]) -> Optional[Message]:
        raise NotImplementedError

    async def send(self, channel: str, text: str,
                   thread: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    async def health(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "reason": "not configured",
                    "missing": self.missing_credentials()}
        return {"ok": True}


class SlackConnector(Connector):
    """Slack Events API + Web API.

    Needs a Slack app the user creates in their own workspace: a bot token and
    the signing secret. Neither can be synthesised — they are issued by Slack to
    an app the workspace admin installs.
    """

    name = "slack"
    required_credentials = ["bot_token", "signing_secret"]

    API = "https://slack.com/api"

    def verify(self, body: bytes, headers: Dict[str, str]) -> bool:
        """Slack's v0 request signature.

        Constant-time comparison and a timestamp window, because a signature
        that stays valid forever is a replay waiting to happen.
        """
        secret = self.config.get("signing_secret") or ""
        if not secret:
            return False
        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")
        if not timestamp or not signature:
            return False
        try:
            if abs(time.time() - int(timestamp)) > SIGNATURE_MAX_AGE:
                return False
        except ValueError:
            return False

        base = b"v0:" + timestamp.encode() + b":" + body
        expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse(self, payload: Dict[str, Any]) -> Optional[Message]:
        event = payload.get("event") or {}
        if event.get("type") not in ("message", "app_mention"):
            return None
        # Ignore our own messages, edits and joins — echoing a bot's own output
        # back into it is the classic way to build an infinite loop.
        if event.get("bot_id") or event.get("subtype"):
            return None

        channel = str(event.get("channel") or "")
        text = str(event.get("text") or "")
        bot_id = self.config.get("bot_user_id") or ""
        return Message(
            connector=self.name,
            channel=channel,
            user=str(event.get("user") or ""),
            text=text,
            thread=event.get("thread_ts") or event.get("ts"),
            mentioned=(event.get("type") == "app_mention"
                       or (bool(bot_id) and f"<@{bot_id}>" in text)),
            is_direct=channel.startswith("D"),
            raw=event,
        )

    async def send(self, channel: str, text: str,
                   thread: Optional[str] = None) -> Dict[str, Any]:
        if not self.configured:
            raise ConnectorError(
                "Slack is not configured. Add a bot token and signing secret."
            )
        import httpx

        payload: Dict[str, Any] = {"channel": channel, "text": text[:38_000]}
        if thread:
            payload["thread_ts"] = thread
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(
                    f"{self.API}/chat.postMessage", json=payload,
                    headers={"Authorization": f"Bearer {self.config['bot_token']}",
                             "Content-Type": "application/json; charset=utf-8"},
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ConnectorError(f"Could not reach Slack: {e}")
        if not data.get("ok"):
            raise ConnectorError(f"Slack refused the message: {data.get('error')}")
        return {"ts": data.get("ts"), "channel": data.get("channel")}

    async def health(self) -> Dict[str, Any]:
        base = await super().health()
        if not base["ok"]:
            return base
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(
                    f"{self.API}/auth.test",
                    headers={"Authorization": f"Bearer {self.config['bot_token']}"},
                )
                data = r.json()
        except httpx.HTTPError as e:
            return {"ok": False, "reason": str(e)}
        if not data.get("ok"):
            return {"ok": False, "reason": data.get("error", "auth failed")}
        return {"ok": True, "team": data.get("team"), "bot": data.get("user")}


class TelegramConnector(Connector):
    """Telegram Bot API.

    Simpler than Slack: a single bot token from BotFather, and a secret token
    echoed back in a header on every webhook.
    """

    name = "telegram"
    required_credentials = ["bot_token"]

    def _api(self) -> str:
        return f"https://api.telegram.org/bot{self.config.get('bot_token', '')}"

    def verify(self, body: bytes, headers: Dict[str, str]) -> bool:
        expected = self.config.get("webhook_secret") or ""
        if not expected:
            # Without a configured secret there is nothing to check, and an
            # unauthenticated webhook must not be treated as authentic.
            return False
        return hmac.compare_digest(
            expected, headers.get("x-telegram-bot-api-secret-token", "")
        )

    def parse(self, payload: Dict[str, Any]) -> Optional[Message]:
        msg = payload.get("message") or payload.get("channel_post") or {}
        text = str(msg.get("text") or "")
        if not text:
            return None
        chat = msg.get("chat") or {}
        username = self.config.get("bot_username") or ""
        return Message(
            connector=self.name,
            channel=str(chat.get("id") or ""),
            user=str((msg.get("from") or {}).get("username")
                     or (msg.get("from") or {}).get("id") or ""),
            text=text,
            thread=str(msg.get("message_thread_id")) if msg.get("message_thread_id") else None,
            mentioned=(bool(username) and f"@{username}" in text)
                      or chat.get("type") == "private",
            is_direct=chat.get("type") == "private",
            raw=msg,
        )

    async def send(self, channel: str, text: str,
                   thread: Optional[str] = None) -> Dict[str, Any]:
        if not self.configured:
            raise ConnectorError("Telegram is not configured. Add a bot token.")
        import httpx

        payload: Dict[str, Any] = {"chat_id": channel, "text": text[:4096]}
        if thread:
            payload["message_thread_id"] = thread
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{self._api()}/sendMessage", json=payload)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise ConnectorError(f"Could not reach Telegram: {e}")
        if not data.get("ok"):
            raise ConnectorError(
                f"Telegram refused the message: {data.get('description')}"
            )
        return {"message_id": (data.get("result") or {}).get("message_id")}

    async def health(self) -> Dict[str, Any]:
        base = await super().health()
        if not base["ok"]:
            return base
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as c:
                data = (await c.get(f"{self._api()}/getMe")).json()
        except httpx.HTTPError as e:
            return {"ok": False, "reason": str(e)}
        if not data.get("ok"):
            return {"ok": False, "reason": data.get("description", "auth failed")}
        return {"ok": True, "bot": (data.get("result") or {}).get("username")}


CONNECTORS = {"slack": SlackConnector, "telegram": TelegramConnector}


def build(name: str, config: Optional[Dict[str, str]] = None) -> Connector:
    cls = CONNECTORS.get(name)
    if not cls:
        raise ConnectorError(
            f"Unknown connector. Available: {', '.join(CONNECTORS)}"
        )
    return cls(config)
