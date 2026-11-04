"""AES-256-GCM encryption of single values (decision D-61).

A stored value looks like `v1.<base64url of nonce + ciphertext + tag>`. Every value gets a fresh
random nonce. The secret's *name* is bound to the ciphertext as "associated data": a value copied
from one row into another (the Quotex password into the Telegram hash, say) fails to decrypt instead
of being accepted. GCM is authenticated, so a wrong key or a damaged value is always an error,
never a wrong answer.

The key is 32 random bytes written as base64url text (`SECRET_KEY` in `backend/.env`). A missing or
malformed key is reported when something is encrypted or decrypted, not when the application starts:
the dashboard must open to explain it.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.vault.errors import KeyInvalidError, KeyMissingError, SecretUnreadableError

KEY_BYTES = 32
NONCE_BYTES = 12
VERSION = "v1"

FIX_HINT = "Run `npm run key:create` (see docs/OPERATIONS.md)."


def generate_key() -> str:
    """A new random key, as text for `.env`."""
    return base64.urlsafe_b64encode(secrets.token_bytes(KEY_BYTES)).decode("ascii").rstrip("=")


def parse_key(text: str | None) -> bytes:
    """The 32 key bytes in `text`. Raises `KeyMissingError` or `KeyInvalidError`."""
    if text is None or not text.strip():
        raise KeyMissingError(
            f"SECRET_KEY is not set in backend/.env, so secrets cannot be stored. {FIX_HINT}"
        )
    cleaned = text.strip()
    try:
        raw = base64.urlsafe_b64decode(cleaned + "=" * (-len(cleaned) % 4))
    except (binascii.Error, ValueError) as exc:
        raise KeyInvalidError(
            f"SECRET_KEY in backend/.env is not valid (it must be 32 random bytes written as "
            f"base64 text). If you have no stored secrets to keep: {FIX_HINT}"
        ) from exc
    if len(raw) != KEY_BYTES:
        raise KeyInvalidError(
            f"SECRET_KEY in backend/.env has the wrong length ({len(raw)} bytes instead of "
            f"{KEY_BYTES}). If you have no stored secrets to keep: {FIX_HINT}"
        )
    return raw


class Cipher:
    def __init__(self, key_text: str | None) -> None:
        self._key_text = key_text

    def status(self) -> str:
        """`ok`, `missing` or `invalid`: what the key in `.env` is like (never the key itself)."""
        try:
            parse_key(self._key_text)
        except KeyMissingError:
            return "missing"
        except KeyInvalidError:
            return "invalid"
        return "ok"

    def encrypt(self, name: str, plaintext: str) -> str:
        aes = AESGCM(parse_key(self._key_text))
        nonce = os.urandom(NONCE_BYTES)
        sealed = aes.encrypt(nonce, plaintext.encode("utf-8"), name.encode("utf-8"))
        return f"{VERSION}." + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, name: str, stored: str) -> str:
        """Raises `SecretUnreadableError` for a wrong key or damaged text, and the key errors for a
        missing or malformed key."""
        aes = AESGCM(parse_key(self._key_text))
        try:
            version, _, body = stored.partition(".")
            if version != VERSION:
                raise ValueError("unknown format")
            blob = base64.urlsafe_b64decode(body)
            nonce, sealed = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
            return aes.decrypt(nonce, sealed, name.encode("utf-8")).decode("utf-8")
        except (InvalidTag, ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise SecretUnreadableError(
                "The stored value cannot be read: SECRET_KEY is not the key it was stored with, "
                "or the stored data is damaged. Enter it again to replace it."
            ) from exc
