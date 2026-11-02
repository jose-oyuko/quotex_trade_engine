"""Errors raised by the owner's controls."""

from __future__ import annotations

from app.core.errors import DomainError


class ControlError(DomainError):
    """A control (pause, stop, switch account...) cannot be carried out."""


class UnknownChainError(ControlError):
    """No running chain has that id (it may just have ended)."""


class AccountSwitchRefusedError(ControlError):
    """Switching between demo and real while trades or chains are running is refused: their stakes
    and results belong to the account they started on."""
