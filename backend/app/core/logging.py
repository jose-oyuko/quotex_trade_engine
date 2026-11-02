"""Structured logging: readable in development, JSON in production, always also to a rotating file.

- **Console** (stderr): readable lines in development, JSON in production.
- **File** (`data/logs/engine.log` by default): always JSON lines, rotated by size (10 MB, 5 old
  files by default), so a long-running process never fills the disk and the history of a bad day is
  still there the next morning.
- **Secrets never reach either**: every log record passes through `redact`, which replaces the exact
  values of the configured secrets (Quotex password, Telegram API hash) with `***`, in messages,
  fields and exception text. (Settings already hide them when printed; this covers a library that
  puts one in an error message or a URL.)
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

REDACTED = "***"
MIN_SECRET_LENGTH = 4  # shorter values would blank out ordinary words


def redactor(secrets: Iterable[str]) -> structlog.typing.Processor:
    """A processor that replaces every occurrence of a secret in the record's text."""
    values = sorted({s for s in secrets if len(s) >= MIN_SECRET_LENGTH}, key=len, reverse=True)

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for secret in values:
                value = value.replace(secret, REDACTED)
            return value
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(scrub(v) for v in value)
        return value

    def process(
        _: Any, __: str, event_dict: structlog.typing.EventDict
    ) -> structlog.typing.EventDict:
        if not values:
            return event_dict
        return {key: scrub(value) for key, value in event_dict.items()}

    return process


def configure_logging(
    level: str,
    *,
    json_output: bool,
    log_file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
    secrets: Iterable[str] = (),
) -> None:
    """Route structlog and stdlib logging (uvicorn, sqlalchemy, ...) through one pipeline."""
    # Exceptions become text first, so the redaction below sees them too. Plain tracebacks on
    # purpose: structlog's default "rich" traceback prints local variables and took ~10 s for one
    # database error, which would freeze the event loop (and trading) while logging. It also emits
    # box-drawing characters that Windows consoles cannot encode.
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        redactor(secrets),
    ]
    console: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(), exception_formatter=structlog.dev.plain_traceback
        )
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    def formatter(renderer: structlog.typing.Processor) -> structlog.stdlib.ProcessorFormatter:
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )

    handlers: list[logging.Handler] = []
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter(console))
    handlers.append(console_handler)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        file_handler.setFormatter(formatter(structlog.processors.JSONRenderer()))
        handlers.append(file_handler)

    root = logging.getLogger()
    for old in root.handlers:
        old.close()  # a reconfigured process must not keep the previous log file open
    root.handlers[:] = handlers
    root.setLevel(level)
