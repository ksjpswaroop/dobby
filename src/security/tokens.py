"""
Per-launch loopback authentication (OW row 56).

The API listens on 127.0.0.1 with no authentication. "It's only localhost" is
not a boundary: every other process on the machine can reach it, and any web
page the user visits can issue requests to it from their browser.

The design is the one Jupyter and the Tauri ecosystem settled on:

* A fresh random token each launch, written to ``~/.dobby/runtime.json`` with
  owner-only permissions. Nothing is persisted between runs, so a leaked token
  dies with the process.
* Every ``/api/v1`` route requires ``Authorization: Bearer <token>``.
* One exemption, ``/api/v1/auth/handshake``, which hands the token to the app's
  own frontend. It is safe because CORS already restricts which origins may
  *read* a response: a hostile page can issue the request but the browser will
  not let it see the answer. Requests with no ``Origin`` at all (curl, the Tauri
  webview, tests) are treated as first-party, since a browser always sends one
  cross-origin.

Health checks stay open so a supervisor can probe liveness without a secret.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Optional, Set

import structlog

logger = structlog.get_logger()

RUNTIME_FILE = Path.home() / ".dobby" / "runtime.json"

# Paths reachable without a token.
OPEN_PATHS: Set[str] = {
    "/", "/health", "/api/v1/health", "/api/v1/auth/handshake",
    "/docs", "/redoc", "/openapi.json",
}

# Origins allowed to complete the handshake — the app's own surfaces.
TRUSTED_ORIGINS: Set[str] = {
    "http://localhost:1420", "http://127.0.0.1:1420",
    "http://localhost:3000", "http://localhost:5173",
    "tauri://localhost", "https://tauri.localhost",
}


class TokenManager:
    """Owns the per-launch token and where it is published."""

    def __init__(self, path: Path = RUNTIME_FILE):
        self.path = path
        self._token: Optional[str] = None

    @property
    def token(self) -> str:
        if self._token is None:
            self._token = secrets.token_urlsafe(32)
        return self._token

    def publish(self, port: int = 8000) -> str:
        """Mint a token and write it where the desktop shell can find it."""
        self._token = secrets.token_urlsafe(32)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"token": self._token, "port": port, "pid": os.getpid()}
            self.path.write_text(json.dumps(payload))
            # Owner read/write only. On a shared machine the token file is the
            # weakest link, so this matters more than the token's entropy.
            self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError as e:
            # A read-only home directory must not stop the app booting; the
            # handshake endpoint still works.
            logger.warning("runtime_file_unwritable", path=str(self.path), error=str(e))
        return self._token

    def revoke(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self._token = None

    def verify(self, presented: Optional[str]) -> bool:
        if not presented or self._token is None:
            return False
        # Constant-time: a timing oracle on a local socket is cheap to exploit.
        return secrets.compare_digest(presented, self._token)


_manager: Optional[TokenManager] = None


def get_token_manager() -> TokenManager:
    global _manager
    if _manager is None:
        _manager = TokenManager()
    return _manager


def is_open_path(path: str) -> bool:
    if path in OPEN_PATHS:
        return True
    # Inbound webhooks come from Slack/Telegram, which cannot hold a launch
    # token. They are authenticated instead by provider signature, which is
    # checked before the payload is parsed — see src/connectors/base.py.
    if path.startswith("/api/v1/messaging/") and path.endswith("/webhook"):
        return True
    # FastAPI's docs pull static assets from this prefix.
    return path.startswith("/docs") or path.startswith("/redoc")


def origin_is_trusted(origin: Optional[str]) -> bool:
    """Whether an Origin may complete the handshake.

    No Origin header means a non-browser caller (curl, the Tauri webview, the
    test client). Those are first-party by definition: a browser always sends
    Origin on a cross-origin request, so its absence cannot be forged *by a
    page*, which is the attacker this guards against.
    """
    if origin is None:
        return True
    return origin.rstrip("/") in TRUSTED_ORIGINS


def bearer_from_header(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None
