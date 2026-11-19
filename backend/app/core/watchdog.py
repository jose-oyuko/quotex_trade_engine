"""The stall watchdog (decision D-80): notices when the event loop stops turning, says where it is
stuck, and makes sure Ctrl+C still ends the program.

Everything in the application runs on one event loop. If one piece of code keeps it to itself (on
2026-11-18 a retry loop that never waited froze the engine twice), nothing else can run: no log
line, no answer to the dashboard, no reconnect, and the normal stop never happens. The watchdog is a
thread outside that loop:

- the loop ticks a heartbeat every `beat_s` (a callback, so it costs nothing);
- the thread looks every `check_s`; after `stall_s` without a tick it logs `engine_stalled` with the
  loop thread's stack, once, then every `repeat_s` while it lasts, and `engine_unstalled` after;
- `stop_requested()` (Ctrl+C) starts a clock: if the process is still there `exit_after_s` later,
  the thread ends it (`os._exit`). Whatever was in flight is dealt with by the next start.

It never restarts anything by itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable
from types import FrameType
from typing import Any

import structlog

log = structlog.get_logger()

STALL_S = 10.0
REPEAT_S = 60.0
EXIT_AFTER_S = 15.0

type Exit = Callable[[int], Any]


class LoopWatchdog:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        stall_s: float = STALL_S,
        repeat_s: float = REPEAT_S,
        exit_after_s: float = EXIT_AFTER_S,
        beat_s: float = 0.5,
        check_s: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
        exit_process: Exit = os._exit,
        logger: Any = None,
    ) -> None:
        self._loop = loop
        self._stall_s = stall_s
        self._repeat_s = repeat_s
        self._exit_after_s = exit_after_s
        self._beat_s = beat_s
        self._check_s = check_s
        self._monotonic = monotonic
        self._exit = exit_process
        self._log = logger if logger is not None else log
        self._last_beat = monotonic()
        self._loop_thread: int | None = None
        self._stop_asked_at: float | None = None
        self._stalled_since: float | None = None
        self._last_report: float | None = None
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._beat_handle: asyncio.TimerHandle | None = None
        self.reports = 0  # how many `engine_stalled` lines were written (tests)

    # --- life cycle (call from the event loop's thread) ---

    def start(self) -> None:
        self._loop_thread = threading.get_ident()
        self._last_beat = self._monotonic()
        self._beat()
        self._thread = threading.Thread(target=self._watch, name="loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._done.set()
        if self._beat_handle is not None:
            self._beat_handle.cancel()
            self._beat_handle = None
        if self._thread is not None:
            self._thread.join(timeout=2 * self._check_s)
            self._thread = None

    def stop_requested(self) -> None:
        """The owner asked the program to stop (Ctrl+C): from now on it has `exit_after_s`."""
        if self._stop_asked_at is None:
            self._stop_asked_at = self._monotonic()

    # --- the loop side ---

    def _beat(self) -> None:
        self._last_beat = self._monotonic()
        if not self._done.is_set():
            self._beat_handle = self._loop.call_later(self._beat_s, self._beat)

    # --- the thread side ---

    def _watch(self) -> None:
        while not self._done.wait(self._check_s):
            self.check()

    def check(self) -> None:
        """One look (the thread calls it every `check_s`; tests call it directly)."""
        now = self._monotonic()
        silent = now - self._last_beat
        if silent >= self._stall_s:
            if self._stalled_since is None:
                self._stalled_since = self._last_beat
            if self._last_report is None or now - self._last_report >= self._repeat_s:
                self._last_report = now
                self.reports += 1
                self._log.error(
                    "engine_stalled",
                    seconds=round(silent, 1),
                    where=self._loop_stack(),
                    hint="the engine is stuck; Ctrl+C ends it within "
                    f"{self._exit_after_s:g} s, and the next start deals with open trades",
                )
        elif self._stalled_since is not None:
            self._log.warning("engine_unstalled", seconds=round(now - self._stalled_since, 1))
            self._stalled_since = self._last_report = None
        asked = self._stop_asked_at
        if asked is not None and now - asked >= self._exit_after_s:
            self._log.error(
                "engine_forced_exit",
                seconds=round(now - asked, 1),
                where=self._loop_stack(),
                hint="the program did not stop in time after Ctrl+C, so it was ended",
            )
            self._done.set()
            self._exit(1)

    def _loop_stack(self) -> str:
        frames: dict[int, FrameType] = sys._current_frames()
        frame = frames.get(self._loop_thread) if self._loop_thread is not None else None
        if frame is None:
            return "(the loop's thread is not running)"
        return "".join(traceback.format_stack(frame))[-4000:]


def chain_stop_signal(watchdog: LoopWatchdog) -> Callable[[], None]:
    """Make Ctrl+C (SIGINT, and SIGBREAK on Windows) also start the watchdog's exit clock,
    keeping whatever handler is installed (the server's own). Returns what undoes it. Works only
    from the main thread (in tests the server runs elsewhere: then nothing is changed)."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None
    names = ["SIGINT", "SIGTERM", "SIGBREAK"]
    installed: list[tuple[signal.Signals, Any]] = []
    for name in names:
        number = getattr(signal, name, None)
        if number is None:
            continue
        previous = signal.getsignal(number)

        def handler(signum: int, frame: FrameType | None, previous: Any = previous) -> None:
            watchdog.stop_requested()
            if callable(previous):
                previous(signum, frame)
            elif previous == signal.SIG_DFL and signum == signal.SIGINT:
                raise KeyboardInterrupt

        try:
            signal.signal(number, handler)
        except (ValueError, OSError):
            continue
        installed.append((number, previous))

    def undo() -> None:
        for number, previous in installed:
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(number, previous)

    return undo
