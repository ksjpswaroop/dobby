"""
Encryption-at-rest vault (100-Day Roadmap, Day 88).

Dobby's database holds API keys, connector credentials, and search-provider
tokens in plain columns. That is fine while the file is only readable by its
owner, and not fine the moment the database is on a synced folder, a backup,
or a shared machine. This encrypts those values at rest.

**AES-256-GCM**, so ciphertext is authenticated — a tampered value fails to
decrypt rather than silently returning altered bytes. **The key is derived
from a passphrase with scrypt** and never written to disk; it lives in the OS
keychain (macOS `security`, with an explicit in-memory fallback elsewhere) so
the database and the key are never in the same place.

**Locking is the default state.** A vault that auto-unlocks on boot protects
nothing against someone who has the machine — the whole point is that reading
the file is not enough.

The scope is deliberately *field-level*, not whole-database. Encrypting the
whole SQLite file would mean either SQLCipher (a C dependency and a different
file format that breaks every existing install) or decrypting to a temp file
on every launch, which puts the plaintext right back on disk. Encrypting the
handful of columns that actually hold secrets gets the real security benefit
with none of that.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from src.db.schema import DatabaseManager

logger = structlog.get_logger()

KEYCHAIN_SERVICE = "dobby-vault"
KEYCHAIN_ACCOUNT = "master-key"

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
# scrypt needs 128*N*r bytes = exactly 32 MiB at these parameters, which is
# OpenSSL's default maxmem — so it must be raised explicitly rather than the
# work factor lowered. A vault passphrase is worth the cost.
SCRYPT_MAXMEM = 128 * SCRYPT_N * SCRYPT_R * 2
KEY_BYTES = 32
NONCE_BYTES = 12
PREFIX = "dobbyv1:"

# Settings fields worth protecting. Anything that is a credential; nothing
# that is a preference, because encrypting a theme name is theatre.
SECRET_FIELDS = (
    "tavily_api_key", "brave_api_key", "openai_api_key", "anthropic_api_key",
    "wigolo_token", "symbolica_api_key",
)

# The unlocked key, held only in memory for this process's lifetime.
_session_key: Optional[bytes] = None
# Fallback store for platforms with no keychain integration here.
_memory_keychain: Dict[str, str] = {}


class VaultError(Exception):
    pass


class VaultLocked(VaultError):
    pass


# ---------------------------------------------------------------------------
# Key storage
# ---------------------------------------------------------------------------
def _keychain_available() -> bool:
    return sys.platform == "darwin" and os.path.exists("/usr/bin/security")


def _keychain_set(value: str) -> bool:
    if not _keychain_available():
        _memory_keychain[KEYCHAIN_ACCOUNT] = value
        return False
    try:
        subprocess.run(
            ["/usr/bin/security", "add-generic-password", "-U",
             "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w", value],
            check=True, capture_output=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        _memory_keychain[KEYCHAIN_ACCOUNT] = value
        return False


def _keychain_get() -> Optional[str]:
    if not _keychain_available():
        return _memory_keychain.get(KEYCHAIN_ACCOUNT)
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            check=True, capture_output=True, timeout=10)
        return out.stdout.decode().strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return _memory_keychain.get(KEYCHAIN_ACCOUNT)


def _keychain_delete() -> None:
    _memory_keychain.pop(KEYCHAIN_ACCOUNT, None)
    if _keychain_available():
        try:
            subprocess.run(
                ["/usr/bin/security", "delete-generic-password",
                 "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
                check=False, capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            pass


# ---------------------------------------------------------------------------
# Key derivation & crypto
# ---------------------------------------------------------------------------
def _derive(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt,
                          n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                          maxmem=SCRYPT_MAXMEM, dklen=KEY_BYTES)


def _vault_meta_path():
    from pathlib import Path

    return Path(os.environ.get("DOBBY_VAULT_META",
                               Path.home() / ".dobby" / "vault.json"))


def _read_meta() -> Optional[Dict[str, Any]]:
    path = _vault_meta_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_meta(meta: Dict[str, Any]) -> None:
    import stat
    from pathlib import Path

    path = _vault_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def encrypt_value(plaintext: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(NONCE_BYTES)
    blob = AESGCM(key).encrypt(nonce, (plaintext or "").encode(), None)
    return PREFIX + base64.b64encode(nonce + blob).decode()


def decrypt_value(ciphertext: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not is_encrypted(ciphertext):
        return ciphertext
    raw = base64.b64decode(ciphertext[len(PREFIX):])
    nonce, blob = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, blob, None).decode()
    except Exception:
        # GCM authenticates: this means a wrong key or tampered data, and the
        # two are worth distinguishing from "empty value".
        raise VaultError("Could not decrypt — wrong key, or the value was altered.")


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def status() -> Dict[str, Any]:
    meta = _read_meta()
    return {
        "initialised": meta is not None,
        "unlocked": _session_key is not None,
        "keychain": _keychain_available(),
        "protected_fields": list(SECRET_FIELDS),
        "created_at": (meta or {}).get("created_at"),
        "note": ("The key is derived from your passphrase and stored in the OS "
                 "keychain, never in the database. Locking is the default state."),
    }


def initialise(passphrase: str) -> Dict[str, Any]:
    if _read_meta():
        raise VaultError("The vault is already set up. Use rotate to change the passphrase.")
    if len(passphrase or "") < 10:
        raise VaultError("A vault passphrase needs at least 10 characters.")

    salt = secrets.token_bytes(16)
    key = _derive(passphrase, salt)
    # A known-plaintext check so a wrong passphrase is caught at unlock time
    # rather than surfacing as a mystery decrypt failure later.
    verifier = encrypt_value("dobby-vault-ok", key)

    _write_meta({
        "salt": base64.b64encode(salt).decode(),
        "verifier": verifier,
        "created_at": datetime.utcnow().isoformat(),
        "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P},
    })
    in_keychain = _keychain_set(base64.b64encode(key).decode())

    global _session_key
    _session_key = key
    return {"initialised": True, "unlocked": True, "stored_in_keychain": in_keychain}


def unlock(passphrase: Optional[str] = None) -> Dict[str, Any]:
    """Unlock from the keychain, or from a passphrase if the keychain is empty."""
    meta = _read_meta()
    if not meta:
        raise VaultError("The vault has not been set up yet.")

    global _session_key

    if passphrase:
        salt = base64.b64decode(meta["salt"])
        key = _derive(passphrase, salt)
    else:
        stored = _keychain_get()
        if not stored:
            raise VaultError("No key in the keychain — unlock with your passphrase.")
        key = base64.b64decode(stored)

    try:
        if decrypt_value(meta["verifier"], key) != "dobby-vault-ok":
            raise VaultError("That passphrase is not correct.")
    except VaultError:
        raise VaultError("That passphrase is not correct.")

    _session_key = key
    return {"unlocked": True}


def lock() -> Dict[str, Any]:
    global _session_key
    _session_key = None
    return {"unlocked": False}


def current_key() -> bytes:
    if _session_key is None:
        raise VaultLocked("The vault is locked. Unlock it first.")
    return _session_key


# ---------------------------------------------------------------------------
# Protecting settings
# ---------------------------------------------------------------------------
def protect_settings() -> Dict[str, Any]:
    """Encrypt every secret settings field that is still plaintext."""
    key = current_key()
    from src.settings import get_settings, get_settings_store

    settings = get_settings()
    changes, encrypted = {}, []
    for field in SECRET_FIELDS:
        value = getattr(settings, field, "") or ""
        if value and not is_encrypted(value):
            changes[field] = encrypt_value(value, key)
            encrypted.append(field)

    if changes:
        get_settings_store().update(**changes)
    return {"encrypted": encrypted, "count": len(encrypted)}


def reveal(field: str) -> str:
    """Decrypt one secret for use. Callers should not hold the result."""
    if field not in SECRET_FIELDS:
        raise VaultError(f"{field} is not a protected field.")
    from src.settings import get_settings

    value = getattr(get_settings(), field, "") or ""
    if not is_encrypted(value):
        return value
    return decrypt_value(value, current_key())


def reveal_all() -> Dict[str, str]:
    return {f: reveal(f) for f in SECRET_FIELDS}


def rotate(old_passphrase: str, new_passphrase: str) -> Dict[str, Any]:
    """Re-key the vault and re-encrypt everything under the new key."""
    if len(new_passphrase or "") < 10:
        raise VaultError("A vault passphrase needs at least 10 characters.")
    meta = _read_meta()
    if not meta:
        raise VaultError("The vault has not been set up yet.")

    old_key = _derive(old_passphrase, base64.b64decode(meta["salt"]))
    try:
        if decrypt_value(meta["verifier"], old_key) != "dobby-vault-ok":
            raise VaultError("The current passphrase is not correct.")
    except VaultError:
        raise VaultError("The current passphrase is not correct.")

    # Decrypt everything under the old key *before* replacing it, so a failure
    # part-way through cannot leave values encrypted under a key nobody has.
    from src.settings import get_settings, get_settings_store

    settings = get_settings()
    plaintext: Dict[str, str] = {}
    for field in SECRET_FIELDS:
        value = getattr(settings, field, "") or ""
        plaintext[field] = decrypt_value(value, old_key) if is_encrypted(value) else value

    new_salt = secrets.token_bytes(16)
    new_key = _derive(new_passphrase, new_salt)

    changes = {f: encrypt_value(v, new_key) for f, v in plaintext.items() if v}
    if changes:
        get_settings_store().update(**changes)

    _write_meta({
        "salt": base64.b64encode(new_salt).decode(),
        "verifier": encrypt_value("dobby-vault-ok", new_key),
        "created_at": meta.get("created_at"),
        "rotated_at": datetime.utcnow().isoformat(),
        "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P},
    })
    _keychain_set(base64.b64encode(new_key).decode())

    global _session_key
    _session_key = new_key
    return {"rotated": True, "re_encrypted": len(changes)}


def disable(passphrase: str) -> Dict[str, Any]:
    """Decrypt everything back to plaintext and remove the vault."""
    meta = _read_meta()
    if not meta:
        raise VaultError("The vault has not been set up yet.")
    key = _derive(passphrase, base64.b64decode(meta["salt"]))
    try:
        if decrypt_value(meta["verifier"], key) != "dobby-vault-ok":
            raise VaultError("That passphrase is not correct.")
    except VaultError:
        raise VaultError("That passphrase is not correct.")

    from src.settings import get_settings, get_settings_store

    settings = get_settings()
    changes = {}
    for field in SECRET_FIELDS:
        value = getattr(settings, field, "") or ""
        if is_encrypted(value):
            changes[field] = decrypt_value(value, key)
    if changes:
        get_settings_store().update(**changes)

    _keychain_delete()
    try:
        _vault_meta_path().unlink(missing_ok=True)
    except OSError:
        pass

    global _session_key
    _session_key = None
    return {"disabled": True, "decrypted": len(changes)}
