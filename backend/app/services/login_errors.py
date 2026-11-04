"""Errors the Telegram and Quotex logins share. The messages are for the owner."""

from __future__ import annotations

from app.core.errors import DomainError


class LoginProblem(DomainError):
    """Base of the errors the login steps raise."""


class EngineRunningError(LoginProblem):
    """Logging in or out needs the engine stopped: it is using the login."""


class WrongStepError(LoginProblem):
    """There is no login at the step this request belongs to (it may have timed out)."""
