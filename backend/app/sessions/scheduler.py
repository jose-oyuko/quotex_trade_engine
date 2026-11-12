"""SessionScheduler: opens the pairs of the trading sessions on their schedule (D-71 to D-73).

It works *before* the order path: on a timer it decides that a pair is due, checks that both orders
could be sent, and hands the two legs (a CALL and a PUT on the session's asset) to `ChainManager`
as signals of the session's hidden group. From there they are ordinary chains: the same risk
guard, executor and adapter, and nothing was added to the fast path.

    window opens -> round: check -> open the pair -> both chains end -> pause -> next candle
                      |  a check fails: skip the round, retry at the next candle
                      '- a stop reason (window end, a target, Stop...): no more pairs; the
                         chains already running finish; then the run is `ended`

One run at a time. A run never resumes: what was in progress at a restart ends as `interrupted`.
All waiting goes through the injected `sleep` and the injected clock, so tests drive time by hand.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.domain.enums import (
    RESULT_TRADE_STATUSES,
    ChainStatus,
    Direction,
    RunEndReason,
    RunState,
    SessionMode,
    SignalStatus,
)
from app.domain.ids import new_id
from app.domain.records import (
    GroupSettingsRecord,
    SessionRecord,
    SessionRunRecord,
    SignalRecord,
)
from app.engine.errors import NoActiveRunError, SessionNotLoadedError, SessionRunActiveError
from app.engine.manager import ChainManager
from app.engine.risk import KEY_KILL_SWITCH, RiskGuard
from app.events.bus import EventBus, OverflowPolicy, Subscription, SubscriptionClosedError
from app.events.types import (
    ChainEnded,
    Event,
    SessionRunChanged,
    SettingChanged,
    SignalReceived,
    TradeSettled,
)
from app.quotex.base import ConnectionState, QuotexAdapter
from app.quotex.errors import QuotexError
from app.sessions.schedule import (
    SEARCH_DAYS,
    Window,
    next_boundary,
    window_length,
    windows_between,
)
from app.signals.models import Signal

log = structlog.get_logger()

type Sleeper = Callable[[float], Awaitable[None]]

TICK_S = 30.0  # the longest a wait lasts before the situation is looked at again
PREPARE_S = 60.0  # the asset is made ready this long before a window opens
PREPARE_TIMEOUT_S = 20.0
START_GRACE_S = 5.0  # a window whose start passed this recently is still started
ALIGN_GRACE_S = 5.0  # an order placed this soon after a candle began counts as on its boundary
DRAIN_ATTEMPTS = 200  # turns of the event loop given to the event consumer before a run ends


@dataclass(slots=True, frozen=True)
class SessionConfig:
    """A session with the strategy settings of its hidden group, as the scheduler needs them."""

    session: SessionRecord
    settings: GroupSettingsRecord

    @property
    def id(self) -> int:
        if self.session.id is None:
            raise ValueError("the session has not been stored yet (no id)")
        return self.session.id


@dataclass(slots=True)
class _Run:
    record: SessionRunRecord
    cfg: SessionConfig
    first_at: datetime
    window_end: datetime
    stop_reason: RunEndReason | None = None
    chains: dict[UUID, int] = field(default_factory=dict)  # running chains -> their pair number
    legs: dict[int, int] = field(default_factory=dict)  # pair number -> legs opened
    refused_legs: dict[int, int] = field(default_factory=dict)  # pair -> legs refused at step 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[Any] | None = None

    @property
    def stopping(self) -> bool:
        return self.stop_reason is not None


class SessionScheduler:
    def __init__(
        self,
        *,
        manager: ChainManager,
        guard: RiskGuard,
        adapter: QuotexAdapter,
        bus: EventBus,
        clock: Clock,
        tasks: TaskSupervisor,
        sleep: Sleeper = asyncio.sleep,
        tick_s: float = TICK_S,
    ) -> None:
        self._manager = manager
        self._guard = guard
        self._adapter = adapter
        self._bus = bus
        self._clock = clock
        self._tasks = tasks
        self._sleep = sleep
        self._tick_s = tick_s
        self._sessions: dict[int, SessionConfig] = {}
        self._last_started: dict[int, datetime] = {}
        self._prepared: set[tuple[int, datetime]] = set()
        self._run: _Run | None = None
        self._chain_run: dict[UUID, _Run] = {}
        self._wake = asyncio.Event()
        self._subscription: Subscription | None = None
        self._background: list[asyncio.Task[Any]] = []

    # --- what the dashboard and the API ask ---

    @property
    def active_run(self) -> SessionRunRecord | None:
        return self._run.record if self._run is not None else None

    def active_run_of(self, session_id: int) -> SessionRunRecord | None:
        run = self._run
        return run.record if run is not None and run.record.session_id == session_id else None

    # --- the sessions the engine knows (the API tells it when one is saved, edited or deleted) ---

    def set_session(self, config: SessionConfig) -> None:
        self._sessions[config.id] = config
        self._wake.set()

    def remove_session(self, session_id: int) -> None:
        self._sessions.pop(session_id, None)
        self._last_started.pop(session_id, None)
        self._wake.set()

    # --- life cycle ---

    def start(self) -> None:
        if self._subscription is not None:
            raise RuntimeError("SessionScheduler already started")
        self._subscription = self._bus.subscribe(
            ChainEnded,
            TradeSettled,
            SettingChanged,
            maxsize=100_000,
            policy=OverflowPolicy.DROP_NEWEST,
            name="sessions",
        )
        self._background = [
            self._tasks.spawn(self._consume(self._subscription), name="sessions-events"),
            self._tasks.spawn(self._loop(), name="sessions-loop"),
        ]

    async def stop(self) -> None:
        """No more pairs and no more timers. A run in progress ends as `engine_stopped` (its
        chains are stopped by the manager, which the engine does next)."""
        if self._subscription is not None:
            self._bus.unsubscribe(self._subscription)
            self._subscription = None
        run = self._run
        tasks = [*self._background, *([run.task] if run and run.task else [])]
        self._background = []
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if run is not None and run.record.state is not RunState.ENDED:
            self._end_run(run, RunEndReason.ENGINE_STOPPED)

    def recover(self, unfinished: list[SessionRunRecord]) -> int:
        """Runs still marked as going at start-up belong to a process that died: they end as
        `interrupted` and are never resumed (decision D-73). Returns how many."""
        now = self._clock.now()
        for record in unfinished:
            self._bus.publish(
                SessionRunChanged(
                    occurred_at=now,
                    run=replace(
                        record,
                        state=RunState.ENDED,
                        end_reason=RunEndReason.INTERRUPTED,
                        ended_at=now,
                        updated_at=now,
                        note="the application stopped while this run was in progress",
                    ),
                )
            )
        return len(unfinished)

    # --- the owner's controls ---

    def start_now(self, session_id: int) -> SessionRunRecord:
        """Begin a run at once, for a window of the session's usual length; the first pair goes
        out immediately (not at a candle boundary)."""
        config = self._sessions.get(session_id)
        if config is None:
            raise SessionNotLoadedError("The engine does not know this session yet; try again.")
        if self._run is not None:
            raise SessionRunActiveError(
                f"A session is already running (run of session {self._run.record.session_id}): "
                "only one session runs at a time. Stop it first."
            )
        now = self._clock.now()
        length = window_length(config.session.start_time, config.session.end_time)
        return self._begin_run(config, "manual", first_at=now, window_end=now + length).record

    def stop_run(self, session_id: int | None = None) -> SessionRunRecord:
        """No new pairs from now on; the chains already running finish (decision D-72)."""
        run = self._run
        if run is None or (session_id is not None and run.record.session_id != session_id):
            raise NoActiveRunError("This session has no run in progress.")
        self._begin_stop(run, RunEndReason.STOPPED)
        return run.record

    # --- the loop that waits for windows ---

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("session_scheduler_error")
                await self._sleep(5.0)

    async def _tick(self) -> None:
        now = self._clock.now()
        planned = self._next_planned(now)
        if planned is None:
            await self._pause(None)
            return
        config, window = planned
        prepare_at = window.start - timedelta(seconds=PREPARE_S)
        if now < prepare_at:
            await self._pause(prepare_at)
            return
        key = (config.id, window.start)
        if key not in self._prepared:
            self._prepared = {k for k in self._prepared if k[1] > now - timedelta(days=1)}
            self._prepared.add(key)
            await self._prepare(config)
            return  # the situation may have changed while the asset was prepared
        if now < window.start:
            await self._pause(window.start)
            return
        self._last_started[config.id] = window.start
        if self._run is not None:
            log.warning(
                "session_window_skipped",
                session=config.session.name,
                reason="another session is running",
            )
            return
        self._begin_run(config, "schedule", first_at=window.start, window_end=window.end)

    def _next_planned(self, now: datetime) -> tuple[SessionConfig, Window] | None:
        """The earliest window still to start. Windows that began more than a moment ago are not
        offered: a window open when the engine starts is never started by itself (decision D-73)."""
        since = now - timedelta(seconds=START_GRACE_S)
        best: tuple[SessionConfig, Window] | None = None
        for config in self._sessions.values():
            session = config.session
            if not session.enabled:
                continue
            last = self._last_started.get(config.id)
            for window in windows_between(session, since, since + timedelta(days=SEARCH_DAYS)):
                if last is not None and window.start <= last:
                    continue
                if best is None or window.start < best[1].start:
                    best = (config, window)
                break
        return best

    async def _prepare(self, config: SessionConfig) -> None:
        """Do the one-time per-asset work ahead of the first order, so that order does not pay
        for it. Best effort: a failure here shows up as a skipped round, with its reason."""
        session = config.session
        try:
            await asyncio.wait_for(
                self._adapter.prepare_asset(session.asset, session.duration_s), PREPARE_TIMEOUT_S
            )
        except Exception as exc:
            log.warning("session_prepare_failed", asset=session.asset, error=str(exc)[:200])

    async def _pause(self, until: datetime | None) -> None:
        """Wait until `until` (at most one tick), or until a session is saved or removed."""
        self._wake.clear()
        timeout = self._tick_s
        if until is not None:
            timeout = min(timeout, (until - self._clock.now()).total_seconds())
        if timeout <= 0:
            await asyncio.sleep(0)
            return
        await _race(self._sleep(timeout), self._wake.wait())

    # --- a run ---

    def _begin_run(
        self, config: SessionConfig, started_by: str, *, first_at: datetime, window_end: datetime
    ) -> _Run:
        now = self._clock.now()
        record = SessionRunRecord(
            id=new_id(),
            session_id=config.id,
            started_by=started_by,
            account_type=self._adapter.account_type,
            started_at=now,
            window_end=window_end,
            state=RunState.RUNNING,
            updated_at=now,
        )
        run = _Run(record=record, cfg=config, first_at=first_at, window_end=window_end)
        self._run = run
        self._bus.publish(SessionRunChanged(occurred_at=now, run=record))
        log.info(
            "session_run_started",
            session=config.session.name,
            started_by=started_by,
            window_end=window_end.isoformat(),
        )
        run.task = self._tasks.spawn(self._drive(run), name=f"session-run-{record.id}")
        return run

    async def _drive(self, run: _Run) -> None:
        try:
            await self._rounds(run)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("session_run_crashed", session=run.cfg.session.name)
            self._update(run, note=f"internal error: {type(exc).__name__}: {exc}"[:500])
            self._begin_stop(run, RunEndReason.ERROR)
        while run.chains:
            await self._wait(run, None)
        await self._drain_events()
        self._end_run(run, run.stop_reason or RunEndReason.ERROR)

    async def _rounds(self, run: _Run) -> None:
        session = run.cfg.session
        await self._wait_until(run, run.first_at)
        while not run.stopping:
            if (reason := self._reason_to_stop(run)) is not None:
                self._begin_stop(run, reason)
                break
            every_candle = session.mode is SessionMode.EVERY_CANDLE
            open_pairs = self._open_pairs(run)
            problem: str | None = None
            opened = False
            if every_candle and open_pairs >= session.max_open_pairs:
                # the limit: this candle gets no pair, and the run says so
                self._skip_round(
                    run,
                    f"{open_pairs} pair(s) are already open: the limit is {session.max_open_pairs}",
                )
            else:
                problem = self._pair_problem(run.cfg)
                opened = problem is None and self._open_pair(run)
                if problem is not None:
                    self._skip_round(run, problem)
            if run.stopping:
                break
            if opened and not every_candle:
                await self._wait_pair_over(run)
                if run.stopping:
                    break
                ready = self._clock.now() + timedelta(seconds=session.pause_s)
                next_at = next_boundary(
                    ready - timedelta(seconds=ALIGN_GRACE_S), session.duration_s
                )
            else:
                # every candle: whatever is still running keeps running; the next pair is for the
                # next candle. A skipped round (either mode) is tried again at the next candle.
                next_at = next_boundary(self._clock.now(), session.duration_s, after=True)
            if next_at >= run.window_end:
                self._begin_stop(run, RunEndReason.WINDOW_ENDED)
                break
            await self._wait_until(run, next_at)

    def _open_pairs(self, run: _Run) -> int:
        """Pairs with at least one chain still running."""
        self._reconcile(run)
        return len(set(run.chains.values()))

    def _reason_to_stop(self, run: _Run) -> RunEndReason | None:
        session, record = run.cfg.session, run.record
        if self._clock.now() >= run.window_end:
            return RunEndReason.WINDOW_ENDED
        if self._guard.kill_switch:
            return RunEndReason.KILL_SWITCH
        if session.profit_target is not None and record.profit >= session.profit_target:
            return RunEndReason.PROFIT_TARGET
        if session.loss_limit is not None and record.profit <= -session.loss_limit:
            return RunEndReason.LOSS_LIMIT
        if session.max_pairs is not None and record.pairs_opened >= session.max_pairs:
            return RunEndReason.MAX_PAIRS
        return None

    def _pair_problem(self, config: SessionConfig) -> str | None:
        """Why a pair cannot be opened right now (both orders are checked before either is sent),
        or None. Everything is read from memory."""
        session, settings = config.session, config.settings
        if (blocked := self._guard.signal_block_reason(session.group_id)) is not None:
            return blocked
        if self._adapter.state is not ConnectionState.CONNECTED:
            return "Quotex is not connected"
        if not self._adapter.is_open(session.asset):
            return f"{session.asset} is closed (or unknown to Quotex)"
        try:
            payout = self._adapter.payout(session.asset, session.duration_s // 60)
        except QuotexError as exc:
            return f"the payout of {session.asset} cannot be read: {exc}"
        if payout is None:
            return f"the payout of {session.asset} is not known"
        if payout < settings.min_payout_pct:
            return (
                f"the payout of {session.asset} is {payout}%, below the minimum "
                f"{settings.min_payout_pct}%"
            )
        return None

    def _open_pair(self, run: _Run) -> bool:
        """Hand both legs to the manager, one straight after the other (no waiting in between).
        False if the first was not started: then nothing was sent."""
        session = run.cfg.session
        number = run.record.pairs_opened + 1
        for direction in (Direction.CALL, Direction.PUT):
            chain_id = self._open_leg(run, number, direction)
            if chain_id is None:
                if number not in run.legs:
                    self._skip_round(run, "the first order of the pair was refused: see the inbox")
                    return False
                break
            run.chains[chain_id] = number
            run.legs[number] = run.legs.get(number, 0) + 1
            self._chain_run[chain_id] = run
        self._update(run, pairs_opened=number)
        self._refresh_lopsided(run, number)
        if session.max_pairs is not None and number >= session.max_pairs:
            self._begin_stop(run, RunEndReason.MAX_PAIRS)
        return True

    def _open_leg(self, run: _Run, number: int, direction: Direction) -> UUID | None:
        session = run.cfg.session
        now = self._clock.now()
        stamp = self._clock.monotonic_ns()
        text = (
            f"{session.name}: pair {number}, {direction.value.upper()} {session.asset} "
            f"{session.duration_s // 60}m"
        )
        signal = Signal(
            id=new_id(),
            group_id=session.group_id,
            asset=session.asset,
            direction=direction,
            duration_s=session.duration_s,
            received_at=now,
            entry_at=None,
            t_msg_received_ns=stamp,
            t_parsed_ns=stamp,
            raw_text=text,
        )
        # The chain row points at this inbox row, so it is published first
        self._bus.publish(
            SignalReceived(
                occurred_at=now,
                signal=SignalRecord(
                    id=signal.id,
                    group_id=signal.group_id,
                    telegram_message_id=None,
                    received_at=now,
                    raw_text=text,
                    status=SignalStatus.PARSED,
                    asset=signal.asset,
                    direction=direction,
                    duration_s=signal.duration_s,
                ),
            )
        )
        return self._manager.open_session_chain(signal, run_id=run.record.id, pair_no=number)

    def _skip_round(self, run: _Run, reason: str) -> None:
        log.info("session_round_skipped", session=run.cfg.session.name, reason=reason)
        self._update(run, rounds_skipped=run.record.rounds_skipped + 1, note=reason[:500])

    async def _wait_pair_over(self, run: _Run) -> None:
        """Sequential mode: nothing else opens until both chains of the pair have ended."""
        while run.chains and not run.stopping:
            if self._clock.now() >= run.window_end:
                self._begin_stop(run, RunEndReason.WINDOW_ENDED)
                return
            await self._wait(run, run.window_end)

    async def _wait_until(self, run: _Run, target: datetime) -> None:
        while not run.stopping and self._clock.now() < target:
            await self._wait(run, target)

    async def _wait(self, run: _Run, until: datetime | None) -> None:
        """Wait at most a tick (or until `until`), or until something happens to the run."""
        run.changed.clear()
        self._reconcile(run)
        timeout = self._tick_s
        if until is not None:
            timeout = min(timeout, (until - self._clock.now()).total_seconds())
        if timeout <= 0:
            await asyncio.sleep(0)
            return
        await _race(self._sleep(timeout), run.changed.wait())

    def _reconcile(self, run: _Run) -> None:
        """A safety net: forget chains the manager no longer runs, in case an event was lost."""
        running = {c.id for c in self._manager.active_chains(run.cfg.session.group_id)}
        for chain_id in [c for c in run.chains if c not in running]:
            run.chains.pop(chain_id, None)

    async def _drain_events(self) -> None:
        """Give the event consumer the turns it needs to book every trade of the run."""
        subscription = self._subscription
        for _ in range(DRAIN_ATTEMPTS):
            if subscription is None or not subscription.depth:
                return
            await asyncio.sleep(0)

    # --- stopping and ending ---

    def _begin_stop(self, run: _Run, reason: RunEndReason) -> None:
        """No more pairs. The first reason is the one recorded."""
        if run.stopping or run.record.state is RunState.ENDED:
            return
        run.stop_reason = reason
        log.info("session_run_stopping", session=run.cfg.session.name, reason=reason.value)
        self._update(run, state=RunState.STOPPING)
        run.changed.set()

    def _end_run(self, run: _Run, reason: RunEndReason) -> None:
        now = self._clock.now()
        self._update(run, state=RunState.ENDED, end_reason=reason, ended_at=now)
        for chain_id in [c for c, r in self._chain_run.items() if r is run]:
            del self._chain_run[chain_id]
        if self._run is run:
            self._run = None
        self._wake.set()
        log.info(
            "session_run_ended",
            session=run.cfg.session.name,
            reason=reason.value,
            pairs=run.record.pairs_opened,
            profit=str(run.record.profit),
        )

    def _update(self, run: _Run, **changes: Any) -> None:
        run.record = replace(run.record, updated_at=self._clock.now(), **changes)
        self._bus.publish(SessionRunChanged(occurred_at=run.record.updated_at, run=run.record))

    # --- what happened to the chains ---

    async def _consume(self, subscription: Subscription) -> None:
        while True:
            try:
                event = await subscription.get()
            except SubscriptionClosedError:
                return
            try:
                self._handle(event)
            except Exception:
                log.exception("session_event_failed", event_name=event.name)

    def _handle(self, event: Event) -> None:
        match event:
            case TradeSettled(trade=trade):
                run = self._chain_run.get(trade.chain_id)
                if run is None or trade.profit is None or trade.status not in RESULT_TRADE_STATUSES:
                    return
                self._update(run, profit=run.record.profit + trade.profit)
                if (reason := self._reason_to_stop(run)) is not None:
                    self._begin_stop(run, reason)
            case ChainEnded(chain=chain):
                run = self._chain_run.pop(chain.id, None)
                if run is None:
                    return
                run.chains.pop(chain.id, None)
                if chain.status is ChainStatus.FAILED and chain.step == 0 and chain.pair_no:
                    self._note_refused_leg(run, chain.pair_no)
                run.changed.set()
            case SettingChanged(setting=setting):
                run = self._run
                if run is not None and setting.key == KEY_KILL_SWITCH and setting.value is True:
                    self._begin_stop(run, RunEndReason.KILL_SWITCH)

    def _note_refused_leg(self, run: _Run, number: int) -> None:
        run.refused_legs[number] = run.refused_legs.get(number, 0) + 1
        self._refresh_lopsided(run, number)

    def _refresh_lopsided(self, run: _Run, number: int) -> None:
        """A pair is lopsided when exactly one of its legs is exposed: the second order was
        refused outright, or a limit refused one of the two at its first order. (Both refused is
        not: nothing was exposed.)"""
        lopsided = sum(
            1 for n, opened in run.legs.items() if opened - run.refused_legs.get(n, 0) == 1
        )
        if lopsided != run.record.lopsided_pairs:
            self._update(
                run,
                lopsided_pairs=lopsided,
                note=f"pair {number}: only one leg is running (the other order was refused)",
            )


async def _race(*waits: Awaitable[Any]) -> None:
    """Return when the first of the awaitables finishes; the others are cancelled."""
    futures = [asyncio.ensure_future(w) for w in waits]
    try:
        await asyncio.wait(futures, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        await asyncio.gather(*futures, return_exceptions=True)
