"""Base of the application's exception hierarchy (docs/CONVENTIONS.md, "Errors and logging")."""

from __future__ import annotations


class DomainError(Exception):
    """An expected failure with a message that is safe to show to the owner."""
