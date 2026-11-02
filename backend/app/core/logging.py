"""Structured logging: readable in development, JSON in production."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str, *, json_output: bool) -> None:
    """Route structlog and stdlib logging (uvicorn, sqlalchemy, ...) through one pipeline."""
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    # Plain tracebacks on purpose: structlog's default "rich" traceback prints local variables and
    # took ~10 s for one database error, which would freeze the event loop (and trading) while
    # logging. It also emits box-drawing characters that Windows consoles cannot encode.
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(), exception_formatter=structlog.dev.plain_traceback
        )
    )
    exception_processors: list[structlog.typing.Processor] = (
        [structlog.processors.format_exc_info] if json_output else []
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *exception_processors,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
