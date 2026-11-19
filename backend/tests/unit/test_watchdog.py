"""The stall watchdog (decision D-80): a frozen event loop is reported with where it is stuck, and
Ctrl+C ends the program even then."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.watchdog import LoopWatchdog


class Recorder:
    """Stands in for the logger: keeps every line."""

    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def error(self, event: str, **fields: Any) -> None:
        self.lines.append({"event": event, **fields})

    warning = error


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def frozen_in_place() -> None:
    """Keeps the event loop to itself, like the retry loop of 2026-11-18."""
    time.sleep(0.6)


async def test_a_frozen_loop_is_reported_with_where_it_is_stuck() -> None:
    logs = Recorder()
    watchdog = LoopWatchdog(
        asyncio.get_running_loop(),
        stall_s=0.2,
        beat_s=0.02,
        check_s=0.05,
        repeat_s=60,
        logger=logs,
    )
    watchdog.start()
    await asyncio.sleep(0.1)
    frozen_in_place()
    await asyncio.sleep(0.2)  # the loop turns again
    watchdog.stop()
    stalled = [e for e in logs.lines if e["event"] == "engine_stalled"]
    assert len(stalled) == 1  # once, not once per look
    assert "frozen_in_place" in stalled[0]["where"]
    assert any(e["event"] == "engine_unstalled" for e in logs.lines)


async def test_a_healthy_loop_is_never_reported() -> None:
    logs = Recorder()
    watchdog = LoopWatchdog(
        asyncio.get_running_loop(), stall_s=0.2, beat_s=0.02, check_s=0.05, logger=logs
    )
    watchdog.start()
    for _ in range(20):
        await asyncio.sleep(0.02)
    watchdog.stop()
    assert [e for e in logs.lines if e["event"] == "engine_stalled"] == []


def test_a_long_stall_is_reported_again_every_repeat_period() -> None:
    clock = Clock()
    loop = asyncio.new_event_loop()
    try:
        watchdog = LoopWatchdog(loop, stall_s=10, repeat_s=60, monotonic=clock)
        clock.now += 11
        watchdog.check()
        clock.now += 30
        watchdog.check()
        assert watchdog.reports == 1
        clock.now += 31
        watchdog.check()
        assert watchdog.reports == 2
    finally:
        loop.close()


def test_ctrl_c_ends_the_program_when_it_has_not_stopped_in_time() -> None:
    clock = Clock()
    exits: list[int] = []
    loop = asyncio.new_event_loop()
    try:
        watchdog = LoopWatchdog(
            loop,
            exit_after_s=15,
            monotonic=clock,
            exit_process=lambda code: exits.append(code),
            logger=Recorder(),
        )
        watchdog.stop_requested()
        clock.now += 14
        watchdog.check()
        assert exits == []  # a normal stop gets its time
        clock.now += 2
        watchdog.check()
        assert exits == [1]
    finally:
        loop.close()


async def test_ctrl_c_on_a_frozen_loop_ends_the_program() -> None:
    exits: list[Any] = []
    logs = Recorder()
    watchdog = LoopWatchdog(
        asyncio.get_running_loop(),
        stall_s=0.2,
        exit_after_s=0.3,
        beat_s=0.02,
        check_s=0.05,
        exit_process=exits.append,
        logger=logs,
    )
    watchdog.start()
    watchdog.stop_requested()
    frozen_in_place()  # nothing on the loop can run: only the watchdog thread can act
    watchdog.stop()
    assert exits == [1]
    assert any(e["event"] == "engine_forced_exit" for e in logs.lines)
