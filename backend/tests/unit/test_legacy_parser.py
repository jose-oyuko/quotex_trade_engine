from __future__ import annotations

import pytest

from app.domain.enums import Direction
from app.signals.parsers import LegacyV1Parser, ParserRegistry, UnknownParserError
from tests.signal_messages import ENTRY_CONFIRMED, NON_SIGNALS, SIGNALS, Expected

parser = LegacyV1Parser()


@pytest.mark.parametrize(
    ("text", "expected"), [c[1:] for c in SIGNALS], ids=[c[0] for c in SIGNALS]
)
def test_every_supported_format_is_parsed(text: str, expected: Expected) -> None:
    outcome = parser.parse(text)
    assert outcome.signal is not None, outcome.reason
    signal = outcome.signal
    assert signal.base_asset == expected.asset
    assert signal.direction is expected.direction
    assert signal.duration_s == expected.duration_s
    assert signal.entry_time == expected.entry
    assert signal.otc_mentioned is expected.otc
    assert signal.utc_offset == expected.utc_offset
    assert signal.duration_assumed is expected.duration_assumed
    assert signal.extra_signals == expected.extra


@pytest.mark.parametrize(("text",), [(c[1],) for c in NON_SIGNALS], ids=[c[0] for c in NON_SIGNALS])
def test_non_signals_are_not_parsed_and_say_why(text: str) -> None:
    outcome = parser.parse(text)
    assert outcome.signal is None
    assert outcome.reason


def test_the_direction_is_never_guessed() -> None:
    """The old parser defaulted to CALL when it saw a pair but no direction."""
    assert parser.parse("ASSET: EUR/USD | EXPIRATION: M1 | ENTRY: 12:00").signal is None
    assert parser.parse("EUR/USD 12:00").signal is None


@pytest.mark.parametrize(
    ("word", "direction"),
    [
        ("BUY", Direction.CALL),
        ("UP", Direction.CALL),
        ("CALL", Direction.CALL),
        ("SELL", Direction.PUT),
        ("DOWN", Direction.PUT),
        ("PUT", Direction.PUT),
    ],
)
def test_direction_words_map_to_call_and_put(word: str, direction: Direction) -> None:
    outcome = parser.parse(f"EUR/USD;10:00;{word} 🟩")
    assert outcome.signal is not None
    assert outcome.signal.direction is direction


def test_gale_lines_never_change_the_signal() -> None:
    plain = parser.parse("ASSET: USD/JPY (OTC) | EXPIRATION: M1 | DIRECTION: BUY | ENTRY: 07:29")
    with_gales = parser.parse(ENTRY_CONFIRMED)
    assert plain.signal == with_gales.signal


def test_a_gale_mention_on_the_signal_line_does_not_drop_the_signal() -> None:
    outcome = parser.parse("USD/INR;03:30;PUT 🟥 (up to 2 gales)")
    assert outcome.signal is not None
    assert outcome.signal.direction is Direction.PUT


def test_a_gale_line_that_names_a_pair_and_direction_is_still_not_a_signal() -> None:
    outcome = parser.parse("1ST GALE — EUR/USD;19:00;CALL")
    assert outcome.signal is None


def test_the_expiry_is_read_from_a_hyphenated_header() -> None:
    outcome = parser.parse("5-minute signal\nUSD/INR;03:30;PUT")
    assert outcome.signal is not None
    assert outcome.signal.duration_s == 300
    assert outcome.signal.duration_assumed is False


def test_a_message_that_is_far_too_long_cannot_hang_the_parser() -> None:
    outcome = parser.parse("EUR/USD " * 50_000)
    assert outcome.signal is None


@pytest.mark.parametrize(
    "garbage", ["\x00\x01", "🟢" * 500, "A/" * 3000, ";" * 3000, "ASSET:" * 1000]
)
def test_the_parser_never_raises(garbage: str) -> None:
    assert isinstance(parser.parse(garbage).reason, str)


def test_the_registry_finds_parsers_by_name() -> None:
    registry = ParserRegistry()
    assert registry.get("legacy_v1") is not None
    assert registry.names == ["legacy_v1"]
    with pytest.raises(UnknownParserError, match="legacy_v1"):
        registry.get("nope")


def test_registering_a_name_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="already registered"):
        ParserRegistry([LegacyV1Parser(), LegacyV1Parser()])
