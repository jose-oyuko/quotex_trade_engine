"""The parser interface. A group chooses its parser by name (`GroupSettingsRecord.parser`)."""

from __future__ import annotations

from typing import Protocol

from app.signals.models import ParseOutcome


class SignalParser(Protocol):
    name: str

    def parse(self, text: str) -> ParseOutcome:
        """Read one message. Must be pure and fast (it runs on the path to the order), must never
        raise for any text, and must not guess: a missing direction means "not a signal"."""
        ...
