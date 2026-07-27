"""
The issuing/verifying authority — what runs on the real license server.

Reachable here as ordinary FastAPI routes purely for development convenience
(there is no deployed server yet, and billing is deferred — see the package
docstring). The seam that matters: **the private key never leaves this
module's storage directory**, which is deliberately outside `~/.dobby/` (the
app's own data directory) so the boundary between "server-side secret" and
"what ships in the app" stays visually obvious even while both happen to run
on the same laptop during development.

A license is a signed, self-contained token — `issue()` returns it directly
rather than an opaque id, because there is no checkout flow yet to fetch it
from. Revocation cannot be encoded in the token itself (a revoked token must
stop working retroactively), so it is checked against the `licenses` table on
every *online* verification; the client-side offline check
(`src.licensing.client`) only checks the signature and expiry, which is why an
online check-in matters at all beyond pure cryptography.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)
from cryptography.exceptions import InvalidSignature

from src.db.license_models import License
from src.db.schema import DatabaseManager

TIERS = ("pro", "team", "white_label")

# Deliberately NOT under ~/.dobby — that is the app's own data directory, which
# a shipped build reads from. A private signing key has no business anywhere
# near it, even in dev, so the separation is visible in the path itself.
AUTHORITY_DIR = Path.home() / ".dobby-license-authority"
PRIVATE_KEY_PATH = AUTHORITY_DIR / "signing_key.pem"
PUBLIC_KEY_PATH = AUTHORITY_DIR / "signing_key.pub"


class LicenseError(Exception):
    """User-facing message."""


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------
def _generate_keypair() -> Ed25519PrivateKey:
    AUTHORITY_DIR.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    AUTHORITY_DIR.chmod(0o700)
    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    )
    PRIVATE_KEY_PATH.chmod(0o600)
    PUBLIC_KEY_PATH.write_bytes(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    return private_key


def get_private_key() -> Ed25519PrivateKey:
    """Load the authority's signing key, generating one on first use."""
    if not PRIVATE_KEY_PATH.exists():
        return _generate_keypair()
    raw = PRIVATE_KEY_PATH.read_bytes()
    return Ed25519PrivateKey.from_private_bytes(raw)


def get_public_key_b64() -> str:
    """The public half, safe to embed in a shipped client build."""
    if not PUBLIC_KEY_PATH.exists():
        get_private_key()  # generates both files
    return base64.urlsafe_b64encode(PUBLIC_KEY_PATH.read_bytes()).decode()


# ---------------------------------------------------------------------------
# Token format: base64url(payload json) + "." + base64url(signature)
# ---------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload: Dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = get_private_key().sign(body)
    return f"{_b64(body)}.{_b64(signature)}"


def split_token(token: str) -> tuple[Dict[str, Any], bytes, bytes]:
    """Parse a token into (payload, body_bytes, signature_bytes) without
    verifying it — verification is `client.verify_offline`'s job."""
    try:
        body_part, sig_part = (token or "").strip().split(".", 1)
        body = _unb64(body_part)
        signature = _unb64(sig_part)
        payload = json.loads(body)
    except Exception as e:
        raise LicenseError(f"Malformed license key: {e}")
    return payload, body, signature


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------
def issue(db: DatabaseManager, tier: str, email: str = "", seats: int = 1,
          update_days: Optional[int] = 365) -> Dict[str, Any]:
    """Mint a new license and return its signed token.

    `update_days=None` means updates never expire (used sparingly — most
    tiers renew updates annually per doc 08 §3). The license itself never
    expires; only the *updates* entitlement does, and a lapsed one still runs.
    """
    if tier not in TIERS:
        raise LicenseError(f"Unknown tier. One of: {', '.join(TIERS)}")
    if seats < 1:
        raise LicenseError("A license needs at least one seat.")

    license_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    updates_until = now + timedelta(days=update_days) if update_days else None

    with db.get_session() as s:
        s.add(License(id=license_id, tier=tier, seats=seats, email=email,
                      issued_at=now, updates_until=updates_until))
        s.commit()

    payload = {
        "lid": license_id, "tier": tier, "seats": seats,
        "iat": now.isoformat(),
        "upd": updates_until.isoformat() if updates_until else None,
    }
    token = _sign(payload)
    return {"license_id": license_id, "token": token, "tier": tier,
            "seats": seats, "updates_until": payload["upd"]}


def revoke(db: DatabaseManager, license_id: str) -> bool:
    with db.get_session() as s:
        lic = s.get(License, license_id)
        if not lic or lic.revoked_at:
            return False
        lic.revoked_at = datetime.now(timezone.utc)
        s.commit()
    return True


# ---------------------------------------------------------------------------
# Authority-side verification (signature + revocation + a fresh server clock)
# ---------------------------------------------------------------------------
def verify(db: DatabaseManager, token: str) -> Dict[str, Any]:
    """Full verification: cryptographic signature, then revocation status.

    Returns a **server-issued timestamp** the client must treat as more
    trustworthy than its own clock — this is the value a client's high-water
    mark advances to, which is what makes rolling the local clock back unable
    to un-expire an update window: the mark came from here, not from the
    machine being checked.
    """
    payload, body, signature = split_token(token)
    public_key = Ed25519PublicKey.from_public_bytes(
        base64.urlsafe_b64decode(get_public_key_b64())
    )
    try:
        public_key.verify(signature, body)
    except InvalidSignature:
        return {"valid": False, "reason": "signature does not match",
                "server_time": datetime.now(timezone.utc).isoformat()}

    license_id = payload.get("lid")
    with db.get_session() as s:
        lic = s.get(License, license_id) if license_id else None

    server_time = datetime.now(timezone.utc)
    if not lic:
        return {"valid": False, "reason": "license not found",
                "server_time": server_time.isoformat()}
    if lic.revoked_at:
        return {"valid": False, "reason": "license revoked",
                "server_time": server_time.isoformat()}

    return {
        "valid": True, "reason": "ok", "license_id": lic.id, "tier": lic.tier,
        "seats": lic.seats,
        "updates_until": lic.updates_until.isoformat() if lic.updates_until else None,
        "server_time": server_time.isoformat(),
    }
