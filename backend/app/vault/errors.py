"""Errors of the secret store. The messages are safe to show to the owner."""

from __future__ import annotations

from app.core.errors import DomainError


class VaultError(DomainError):
    """Base of the secret store's errors."""


class KeyMissingError(VaultError):
    pass


class KeyInvalidError(VaultError):
    pass


class SecretUnreadableError(VaultError):
    """The stored value cannot be decrypted: the key is not the one it was stored with, or the
    stored text was damaged. Never a wrong value: decryption is authenticated."""


class UnknownSecretError(VaultError):
    pass


class InvalidSecretError(VaultError):
    pass
