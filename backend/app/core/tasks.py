"""Supervised background tasks.

Every background task goes through `TaskSupervisor.spawn`, so it keeps a reference (asyncio only
holds weak ones), logs an unhandled exception instead of losing it, and is cancelled and awaited
at shutdown.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

log = structlog.get_logger()


class TaskSupervisor:
    """Owns the background tasks of one application instance."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        """Run `coro` in the background under supervision."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("background_task_failed", task=task.get_name(), exc_info=exc)

    @property
    def running(self) -> int:
        return len(self._tasks)

    async def shutdown(self, grace_seconds: float = 5.0) -> None:
        """Cancel every task and wait for it to finish cleaning up."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=grace_seconds)
            for task in pending:
                log.warning("background_task_did_not_stop", task=task.get_name())
