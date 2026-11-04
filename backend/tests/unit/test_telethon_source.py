"""The parts of the Telethon wrapper that can be checked without a network or an account."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.signals.models import RawMessage
from app.telegram.factory import build_telethon_source
from app.telegram.source import DialogKind, TelegramNotConfiguredError
from app.telegram.telethon_source import (
    TelethonSource,
    describe_code_delivery,
    dialog_info,
    raw_from_event,
)
from tests.signal_support import ManualClock

SENT = datetime(2026, 11, 1, 9, 59, 58, tzinfo=UTC)


def event(
    chat_id: int | None = -1001, text: str | None = "hello", message_id: int = 5
) -> SimpleNamespace:
    return SimpleNamespace(
        chat_id=chat_id, message=SimpleNamespace(id=message_id, message=text, date=SENT)
    )


def make_source(tmp_path: Path) -> TelethonSource:
    return TelethonSource(
        api_id=1, api_hash="hash", session_path=tmp_path / "t", clock=ManualClock()
    )


def test_an_event_becomes_a_raw_message() -> None:
    clock = ManualClock()
    raw = raw_from_event(event(), edited=False, clock=clock)
    assert raw == RawMessage(
        chat_id=-1001,
        message_id=5,
        text="hello",
        received_at=clock.now(),
        received_ns=raw.received_ns if raw else 0,
        sent_at=SENT,
        edited=False,
    )


def test_media_without_text_becomes_an_empty_message_and_edits_are_flagged() -> None:
    raw = raw_from_event(event(text=None), edited=True, clock=ManualClock())
    assert raw is not None and raw.text == "" and raw.edited is True


def test_events_without_a_chat_or_message_are_skipped() -> None:
    assert raw_from_event(event(chat_id=None), edited=False, clock=ManualClock()) is None
    assert (
        raw_from_event(SimpleNamespace(chat_id=1, message=None), edited=False, clock=ManualClock())
        is None
    )


@pytest.mark.parametrize(
    ("flags", "kind"),
    [
        ({"is_user": True, "is_group": False}, DialogKind.USER),
        ({"is_user": False, "is_group": True}, DialogKind.GROUP),
        ({"is_user": False, "is_group": False}, DialogKind.CHANNEL),
    ],
)
def test_dialogs_are_classified(flags: dict[str, bool], kind: DialogKind) -> None:
    info = dialog_info(SimpleNamespace(id=-100123, name="Alpha signals", **flags))
    assert (info.chat_id, info.title, info.kind) == (-100123, "Alpha signals", kind)


async def test_only_subscribed_chats_are_delivered(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    delivered: list[RawMessage] = []
    source.set_handler(delivered.append)
    source.set_chats(frozenset({-1001}))
    await source._on_new(event(-1001, "yes"))
    await source._on_new(event(-1002, "no"))
    await source._on_edited(event(-1001, "edited"))
    assert [(m.text, m.edited) for m in delivered] == [("yes", False), ("edited", True)]

    source.set_chats(frozenset())  # unsubscribed at runtime
    await source._on_new(event(-1001, "after"))
    assert len(delivered) == 2


async def test_a_crashing_handler_does_not_escape_into_the_library(tmp_path: Path) -> None:
    source = make_source(tmp_path)

    def broken(_: RawMessage) -> None:
        raise RuntimeError("bug in our code")

    source.set_handler(broken)
    source.set_chats(frozenset({-1001}))
    await source._on_new(event())


def test_the_factory_needs_the_api_credentials() -> None:
    with pytest.raises(TelegramNotConfiguredError, match="Telegram API id"):
        build_telethon_source(Settings(_env_file=None), clock=ManualClock())  # type: ignore[call-arg]
    with pytest.raises(TelegramNotConfiguredError):
        build_telethon_source(
            Settings(_env_file=None, telegram_api_id=1, telegram_api_hash="  "),  # type: ignore[call-arg]
            clock=ManualClock(),
        )


def test_the_factory_builds_a_source_with_the_session_in_the_data_directory(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, telegram_api_id=12345, telegram_api_hash="abcdef", data_dir=tmp_path
    )
    assert settings.telegram_session_path == tmp_path.resolve() / "telegram"
    with pytest.raises(TelegramNotConfiguredError, match="not logged in"):
        build_telethon_source(settings, clock=ManualClock())  # no login yet
    (tmp_path / "telegram.session").write_bytes(b"made by the command-line login")
    source = build_telethon_source(settings, clock=ManualClock())
    assert isinstance(source, TelethonSource) and source.session_string() is None  # a file login


def test_the_factory_uses_the_session_made_on_the_dashboard_before_any_file(
    tmp_path: Path,
) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        telegram_api_id=12345,
        telegram_api_hash="abcdef",
        telegram_session="1AbCdEfStringSession",
        data_dir=tmp_path,
    )
    (tmp_path / "telegram.session").write_bytes(b"an older file login")
    source = build_telethon_source(settings, clock=ManualClock())
    assert source._session_string == "1AbCdEfStringSession" and source._session_path is None


def test_a_source_needs_exactly_one_kind_of_session(tmp_path: Path) -> None:
    clock = ManualClock()
    with pytest.raises(ValueError, match="exactly one"):
        TelethonSource(api_id=1, api_hash="h", clock=clock)
    with pytest.raises(ValueError, match="exactly one"):
        TelethonSource(
            api_id=1, api_hash="h", clock=clock, session_path=tmp_path / "t", session_string=""
        )


def test_telegram_settings_are_safe_and_blank_values_mean_unset() -> None:
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert defaults.telegram_api_id is None and defaults.telegram_api_hash is None
    blank = Settings(_env_file=None, telegram_api_id="", telegram_phone="  ")  # type: ignore[call-arg, arg-type]
    assert blank.telegram_api_id is None and blank.telegram_phone is None
    secret = Settings(_env_file=None, telegram_api_hash="topsecrethash")  # type: ignore[call-arg]
    assert "topsecrethash" not in repr(secret) + str(secret) + str(secret.model_dump())


@pytest.mark.parametrize(
    ("kind", "words"),
    [
        ("SentCodeTypeApp", "Telegram app"),
        ("SentCodeTypeSms", "SMS"),
        ("SentCodeTypeFirebaseSms", "SMS"),
        ("SentCodeTypeCall", "phone call"),
        ("SentCodeTypeEmailCode", "e-mail"),
        ("SomethingNew", "SomethingNew"),
    ],
)
def test_the_way_telegram_sent_the_code_is_put_into_words(kind: str, words: str) -> None:
    sent = SimpleNamespace(type=type(kind, (), {})())
    assert words in describe_code_delivery(sent)
