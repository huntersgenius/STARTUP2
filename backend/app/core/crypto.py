"""AES-256-GCM envelope for patient PII.

Patient identifiers never live in queryable columns. They are serialised to
JSON, encrypted with a key held only by the application, and stored as an
opaque blob. A database dump on its own therefore contains no identifiers.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

NONCE_BYTES = 12
_VERSION = b"\x01"


class DecryptionError(RuntimeError):
    """Raised when a PII blob cannot be authenticated or decrypted."""


def _key() -> bytes:
    raw = base64.b64decode(get_settings().pii_encryption_key)
    if len(raw) != 32:
        raise ValueError("PII_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)")
    return raw


def encrypt_blob(payload: dict[str, Any], *, aad: bytes | None = None) -> bytes:
    """Encrypt a JSON-serialisable dict. Returns version || nonce || ciphertext."""
    nonce = os.urandom(NONCE_BYTES)
    plaintext = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = AESGCM(_key()).encrypt(nonce, plaintext, aad)
    return _VERSION + nonce + ciphertext


def decrypt_blob(blob: bytes, *, aad: bytes | None = None) -> dict[str, Any]:
    if not blob or blob[:1] != _VERSION:
        raise DecryptionError("unknown PII blob version")
    nonce, ciphertext = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
    try:
        plaintext = AESGCM(_key()).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:  # tampered or wrong key
        raise DecryptionError("PII blob failed authentication") from exc
    return json.loads(plaintext.decode("utf-8"))
