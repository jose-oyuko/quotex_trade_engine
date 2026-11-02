"""Looks parsers up by the name stored in a group's settings."""

from __future__ import annotations

from app.signals.parsers.base import SignalParser
from app.signals.parsers.legacy_v1 import LegacyV1Parser


class UnknownParserError(KeyError):
    """A group refers to a parser that is not registered."""


class ParserRegistry:
    def __init__(self, parsers: list[SignalParser] | None = None) -> None:
        self._parsers: dict[str, SignalParser] = {}
        for parser in parsers if parsers is not None else [LegacyV1Parser()]:
            self.register(parser)

    def register(self, parser: SignalParser) -> None:
        if parser.name in self._parsers:
            raise ValueError(f"a parser named {parser.name!r} is already registered")
        self._parsers[parser.name] = parser

    def get(self, name: str) -> SignalParser:
        try:
            return self._parsers[name]
        except KeyError:
            known = ", ".join(sorted(self._parsers))
            raise UnknownParserError(f"unknown parser {name!r} (known: {known})") from None

    @property
    def names(self) -> list[str]:
        return sorted(self._parsers)
