"""Logging: a rotating JSON file, and no secret in any line."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import structlog

from app.core.config import Settings
from app.core.logging import REDACTED, configure_logging, redactor


@pytest.fixture(autouse=True)
def restore_logging():  # type: ignore[no-untyped-def]
    """Leave the process the way the test suite expects it (no file handlers, no open files)."""
    yield
    root = logging.getLogger()
    for handler in root.handlers:
        handler.close()
    root.handlers[:] = []
    structlog.configure(  # back to what tests/conftest.py sets up for the rest of the suite
        processors=[
            structlog.dev.ConsoleRenderer(
                colors=False, exception_formatter=structlog.dev.plain_traceback
            )
        ]
    )


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_log_lines_go_to_a_json_file_a_tool_can_read(tmp_path: Path) -> None:
    file = tmp_path / "logs" / "engine.log"  # the folder does not exist yet
    configure_logging("INFO", json_output=False, log_file=file)
    structlog.get_logger().info("trade_placed", asset="EURUSD", step=2)
    logging.getLogger("uvicorn.error").warning("from a library")
    first, second = lines(file)
    assert first["event"] == "trade_placed" and first["asset"] == "EURUSD" and first["step"] == 2
    assert first["level"] == "info" and str(first["timestamp"]).endswith("Z")
    assert second["event"] == "from a library" and second["level"] == "warning"


def test_the_file_is_rotated_by_size_and_old_files_are_pruned(tmp_path: Path) -> None:
    file = tmp_path / "engine.log"
    configure_logging("INFO", json_output=True, log_file=file, max_bytes=1_500, backups=2)
    log = structlog.get_logger()
    for n in range(300):
        log.info("something_happened", number=n, padding="x" * 40)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["engine.log", "engine.log.1", "engine.log.2"]  # at most two old files kept
    assert all(p.stat().st_size <= 1_500 + 300 for p in tmp_path.iterdir())  # about max_bytes each
    newest = [int(str(entry["number"])) for entry in lines(file)]
    older = [int(str(entry["number"])) for entry in lines(tmp_path / "engine.log.1")]
    assert newest[-1] == 299 and max(older) < min(newest)  # newest in the live file, in order


def test_without_a_file_nothing_is_written_to_disk(tmp_path: Path) -> None:
    configure_logging("INFO", json_output=False, log_file=None)
    structlog.get_logger().info("hello")
    assert list(tmp_path.iterdir()) == []


def test_reconfiguring_does_not_keep_the_old_file_open(tmp_path: Path) -> None:
    first = tmp_path / "a.log"
    configure_logging("INFO", json_output=False, log_file=first)
    configure_logging("INFO", json_output=False, log_file=tmp_path / "b.log")
    first.unlink()  # impossible on Windows while a handle is open
    assert not first.exists()


SECRET = "p4ssw0rd-do-not-print"
HASH = "0123456789abcdef0123456789abcdef"


def test_secrets_are_replaced_in_messages_fields_and_nested_values(tmp_path: Path) -> None:
    file = tmp_path / "engine.log"
    configure_logging("INFO", json_output=False, log_file=file, secrets=[SECRET, HASH])
    log = structlog.get_logger()
    log.info(f"login failed for password {SECRET}")
    log.info("connecting", url=f"wss://user:{SECRET}@host/ws", nested={"a": [HASH, "fine"]})
    text = file.read_text(encoding="utf-8")
    assert SECRET not in text and HASH not in text
    first, second = lines(file)
    assert first["event"] == f"login failed for password {REDACTED}"
    assert second["url"] == f"wss://user:{REDACTED}@host/ws"
    assert second["nested"] == {"a": [REDACTED, "fine"]}


def test_secrets_are_replaced_in_exception_text_and_in_library_logs(tmp_path: Path) -> None:
    file = tmp_path / "engine.log"
    configure_logging("INFO", json_output=False, log_file=file, secrets=[SECRET])
    try:
        raise RuntimeError(f"bad credentials: {SECRET}")
    except RuntimeError:
        structlog.get_logger().error("login_failed", exc_info=True)
    logging.getLogger("some.library").error("handshake with %s failed", SECRET)
    text = file.read_text(encoding="utf-8")
    assert SECRET not in text
    entries = lines(file)
    assert "bad credentials" in str(entries[0]["exception"]) and REDACTED in str(
        entries[0]["exception"]
    )
    assert entries[1]["event"] == f"handshake with {REDACTED} failed"


def test_short_values_are_not_treated_as_secrets() -> None:
    process = redactor(["abc", "", "x"])  # a 3-letter "secret" would blank out ordinary words
    assert process(None, "info", {"event": "abc x"}) == {"event": "abc x"}


def test_the_settings_know_which_values_are_secret() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        quotex_password=SECRET,
        telegram_api_hash=HASH,
        quotex_email="me@example.com",
    )
    assert sorted(settings.secret_values()) == sorted([SECRET, HASH])  # the email is not a secret
    assert SECRET not in repr(settings) and HASH not in repr(settings)
    assert Settings(_env_file=None).secret_values() == []  # type: ignore[call-arg]


def test_the_log_file_lives_in_the_data_folder_by_default(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]
    assert settings.log_path == tmp_path.resolve() / "logs" / "engine.log"
    assert (settings.log_to_file, settings.log_max_mb, settings.log_backups) == (True, 10, 5)
