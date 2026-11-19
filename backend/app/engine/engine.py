"""The engine: Telegram -> pipeline -> chain manager -> executor -> broker adapters, wired together,
with the trading-session scheduler (D-71) feeding the same chain manager from a timer.

This is only composition: every rule lives in the component it belongs to. Tests build it with the
fake Telegram source and fake adapters; the application builds it with the real ones. Without a
Telegram source (none is logged in) the engine runs with signals off: trading sessions still work.

There is one adapter per broker that has a login, Quotex and Deriv side by side (decision D-75).
They share one demo/real switch and one real-money permission. The owner can switch either broker
off and on while the engine runs (decision D-81): an off broker is not connected, and what would
trade on it is skipped with that reason.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import structlog

from app.brokers.base import BrokerAdapter
from app.brokers.errors import BrokerError
from app.core.backoff import BackoffPolicy
from app.core.clock import Clock
from app.core.tasks import TaskSupervisor
from app.db.recovery import RecoveryState
from app.domain.enums import AccountType, Broker, GroupSource
from app.domain.ids import new_id
from app.domain.records import GroupRecord, GroupSettingsRecord, RiskEventRecord, SessionRecord
from app.engine.errors import (
    AccountSwitchRefusedError,
    BrokerSwitchRefusedError,
    TelegramNotConnectedError,
)
from app.engine.executor import RESULT_MARGIN_S, Executor
from app.engine.manager import ChainManager, RecoverySummary
from app.engine.risk import RiskGuard, RiskLimits
from app.events.bus import EventBus
from app.events.types import AccountChanged, RiskTripped
from app.sessions.scheduler import TICK_S, SessionConfig, SessionScheduler
from app.signals.parsers.registry import ParserRegistry
from app.signals.pipeline import GroupRoute, PipelineConfig, SignalPipeline, Sleeper
from app.telegram.listener import ListenerState, TelegramListener
from app.telegram.source import DialogKind, TelegramSource

CHAT_LIST_TIMEOUT_S = 30.0  # listing chats is one request to Telegram; never wait longer than this
DISCONNECT_TIMEOUT_S = 10.0  # the longest one broker may take to close when the engine stops

log = structlog.get_logger()


@dataclass(slots=True, frozen=True)
class ChatChoice:
    """A Telegram group or channel the owner could take signals from."""

    chat_id: int
    title: str
    kind: Literal["group", "channel"]


class Engine:
    def __init__(
        self,
        *,
        adapter: BrokerAdapter | None = None,
        adapters: Mapping[Broker, BrokerAdapter] | None = None,
        source: TelegramSource | None,
        bus: EventBus,
        clock: Clock,
        tasks: TaskSupervisor,
        parsers: ParserRegistry | None = None,
        pipeline_config: PipelineConfig | None = None,
        sleep: Sleeper = asyncio.sleep,
        result_margin_s: float = RESULT_MARGIN_S,
        risk_limits: RiskLimits | None = None,
        telegram_backoff: BackoffPolicy | None = None,
        session_sleep: Sleeper | None = None,
        session_tick_s: float = TICK_S,
    ) -> None:
        brokers: dict[Broker, BrokerAdapter] = dict(adapters or {})
        if adapter is not None:  # the one-broker shorthand (tests): it is Quotex
            brokers.setdefault(Broker.QUOTEX, adapter)
        if not brokers:
            raise ValueError("the engine needs at least one broker")
        self.adapters: Mapping[Broker, BrokerAdapter] = brokers
        self._connecting: dict[Broker, asyncio.Task[None]] = {}
        self._off: set[Broker] = set()  # switched off by the owner (decision D-81)
        self._enabled_groups: set[int] = set()  # Telegram groups that are switched on
        self._source = source
        self._tasks = tasks
        self._bus = bus
        self._clock = clock
        self.guard = RiskGuard(clock=clock, bus=bus, limits=risk_limits)
        self.executor = Executor(
            brokers,
            guard=self.guard,
            clock=clock,
            bus=bus,
            result_margin_s=result_margin_s,
            switched_off=self._off,
        )
        self.manager = ChainManager(
            executor=self.executor, guard=self.guard, bus=bus, clock=clock, tasks=tasks
        )
        self.pipeline = SignalPipeline(
            bus=bus,
            clock=clock,
            parsers=parsers or ParserRegistry(),
            tasks=tasks,
            on_signal=self.manager.on_signal,
            config=pipeline_config,
            sleep=sleep,
        )
        self.listener: TelegramListener | None = (
            None
            if source is None
            else TelegramListener(
                source,
                handler=self.pipeline.handle,
                bus=bus,
                clock=clock,
                tasks=tasks,
                backoff=telegram_backoff,
            )
        )
        self.scheduler = SessionScheduler(
            manager=self.manager,
            guard=self.guard,
            executor=self.executor,
            bus=bus,
            clock=clock,
            tasks=tasks,
            sleep=session_sleep or sleep,
            tick_s=session_tick_s,
        )

    @property
    def account_type(self) -> AccountType:
        """The account every broker is on (one switch for all)."""
        return self.executor.account_type

    def brokers_in_use(self) -> set[Broker]:
        """The brokers an enabled group or session trades on (for the "not connected" banner);
        a broker the owner switched off is not in use."""
        used = {self.manager.group_broker(g) for g in self._enabled_groups}
        used |= {c.session.broker for c in self.scheduler.sessions() if c.session.enabled}
        return used - self._off

    # --- switching a broker off and on (decision D-81) ---

    @property
    def switched_off(self) -> frozenset[Broker]:
        return frozenset(self._off)

    def set_switched_off(self, brokers: set[Broker]) -> None:
        """The stored choice, given before `start`: these brokers are not connected."""
        self._off.clear()
        self._off.update(brokers)

    def login_problem(self, broker: Broker) -> str | None:
        """Why the broker stopped trying and waits for the owner, if it did."""
        adapter = self.adapters.get(broker)
        return None if adapter is None or broker in self._off else adapter.login_problem

    async def set_broker_enabled(self, broker: Broker, enabled: bool) -> None:
        """Switch one broker off (its connection closes, its login attempts stop) or on (it
        connects at once); nothing else is touched. Switching off is refused while something
        trades on it."""
        adapter = self.adapters.get(broker)
        if enabled:
            if adapter is None:
                raise BrokerSwitchRefusedError(
                    f"{broker.label} cannot be switched on: its login is not stored. Store it on "
                    "the Settings page, then restart the engine."
                )
            self._off.discard(broker)
            task = self._connecting.get(broker)
            if task is None or task.done():  # not already connecting (or connected and watched)
                self._start_connecting(broker, adapter)
            log.info("broker_switched_on", broker=broker.value)
            return
        if broker in self._off:
            return
        if (reason := self._in_use(broker)) is not None:
            raise BrokerSwitchRefusedError(
                f"{broker.label} cannot be switched off while {reason}: wait for them to finish, "
                "or stop them first."
            )
        self._off.add(broker)
        task = self._connecting.pop(broker, None)
        if task is not None:
            task.cancel()
        if adapter is not None:
            await self._disconnect(broker, adapter)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        log.info("broker_switched_off", broker=broker.value)

    def _in_use(self, broker: Broker) -> str | None:
        trades = self.guard.open_trades_of(broker)
        if trades:
            return f"{trades} trade(s) are open on it"
        chains = [c for c in self.manager.active_chains() if c.spec.broker is broker]
        if chains:
            return f"{len(chains)} chain(s) are running on it"
        if self.scheduler.active_broker is broker:
            return "a trading session is running on it"
        return None

    def _start_connecting(self, broker: Broker, adapter: BrokerAdapter) -> None:
        self._connecting[broker] = self._tasks.spawn(
            self._connect(broker, adapter), name=f"{broker}-connect"
        )

    @staticmethod
    async def _connect(broker: Broker, adapter: BrokerAdapter) -> None:
        try:
            await adapter.connect(retry_forever=True)
        except BrokerError as exc:  # a login only the owner can fix: the adapter says why
            log.warning("broker_needs_owner", broker=broker.value, error=str(exc)[:300])

    @property
    def telegram_enabled(self) -> bool:
        """False when no Telegram login was available: signals are off, sessions still run."""
        return self.listener is not None

    # --- groups (the API of Phase 6 will call these when a group is created or edited) ---

    def set_group(self, group: GroupRecord, settings: GroupSettingsRecord) -> None:
        self.manager.set_group(settings, group.broker)
        if group.id is not None and group.source is GroupSource.TELEGRAM:
            if group.enabled:
                self._enabled_groups.add(group.id)
            else:
                self._enabled_groups.discard(group.id)
        if group.source is GroupSource.SESSION or group.telegram_chat_id is None:
            return  # a session's hidden group has no chat: only its strategy settings matter
        self.pipeline.set_route(GroupRoute.from_records(group, settings))
        if self.listener is None:
            return
        if group.enabled:
            self.listener.subscribe(group.telegram_chat_id)
        else:
            self.listener.unsubscribe(group.telegram_chat_id)

    def remove_group(self, group: GroupRecord) -> None:
        if group.telegram_chat_id is not None:
            self.pipeline.remove_route(group.telegram_chat_id)
            if self.listener is not None:
                self.listener.unsubscribe(group.telegram_chat_id)
        if group.id is not None:
            self.manager.remove_group(group.id)
            self._enabled_groups.discard(group.id)

    # --- trading sessions (the API calls these when a session is saved, edited or deleted) ---

    def set_session(self, session: SessionRecord, settings: GroupSettingsRecord) -> None:
        self.scheduler.set_session(SessionConfig(session, settings))

    def remove_session(self, session_id: int) -> None:
        self.scheduler.remove_session(session_id)

    async def switch_account(self, account_type: AccountType) -> None:
        """Move between demo and real. Refused while any chain or trade is running (their stakes
        and results belong to the account they started on); real also needs the owner's
        permission."""
        if self.scheduler.active_run is not None:
            raise AccountSwitchRefusedError(
                "a trading session is running: stop it (and let its chains finish) first"
            )
        if self.manager.active_chains() or self.guard.open_trades:
            raise AccountSwitchRefusedError(
                f"{len(self.manager.active_chains())} chain(s) and {self.guard.open_trades} "
                "trade(s) are still running: wait for them or end them first"
            )
        await self._switch_all(account_type)
        now = self._clock.now()
        self._bus.publish(AccountChanged(occurred_at=now, account_type=account_type))
        if account_type is AccountType.REAL:  # the one switch that moves real money: on the record
            self._bus.publish(
                RiskTripped(
                    occurred_at=now,
                    risk_event=RiskEventRecord(
                        id=new_id(),
                        occurred_at=now,
                        kind="switched_to_real",
                        message="The account was switched to REAL money: trades now use real funds",
                        group_id=None,
                    ),
                )
            )

    async def _switch_all(self, account_type: AccountType) -> None:
        """Every broker moves, or none does: a broker that cannot (no real login, no permission)
        refuses the switch, and the ones already moved go back."""
        moved: list[tuple[BrokerAdapter, AccountType]] = []
        for broker, adapter in self.adapters.items():
            before = adapter.account_type
            try:
                await adapter.set_account_type(account_type)
            except BrokerError as exc:
                for done, previous in reversed(moved):
                    with contextlib.suppress(BrokerError):
                        await done.set_account_type(previous)
                if len(self.adapters) == 1:
                    raise
                raise AccountSwitchRefusedError(
                    f"{broker.label} cannot switch to {account_type.value}: {exc}"
                ) from exc
            moved.append((adapter, before))

    def set_real_allowed(self, allowed: bool) -> None:
        for adapter in self.adapters.values():
            adapter.set_real_allowed(allowed)

    # --- Telegram chats (for the "choose a group" picker) ---

    async def list_chats(self, *, timeout_s: float | None = None) -> list[ChatChoice]:
        """The chats the logged-in Telegram account is in. Read-only, and it uses the connection the
        listener already has: asking never starts a second login on the same session file."""
        if (
            self.listener is None
            or self._source is None
            or self.listener.state is not ListenerState.CONNECTED
        ):
            raise TelegramNotConnectedError("Telegram is not connected")
        async with asyncio.timeout(CHAT_LIST_TIMEOUT_S if timeout_s is None else timeout_s):
            dialogs = await self._source.list_dialogs()
        return [
            ChatChoice(
                chat_id=d.chat_id,
                title=d.title,
                kind="group" if d.kind is DialogKind.GROUP else "channel",
            )
            for d in dialogs
            if d.kind is not DialogKind.USER  # signals come from groups and channels
        ]

    # --- life cycle ---

    def load(self, recovery: RecoveryState) -> RecoverySummary:
        """Rebuild the in-memory state from the database: groups first, then what was in flight
        when we last stopped (chains before session runs: a run carried on keeps its chains).
        Runs inside the event loop: Deriv chains carried on get their tasks here."""
        self.guard.load(recovery.app_settings, recovery.recent_settled_trades)
        settings = {s.group_id: s for s in recovery.group_settings}
        for group in recovery.groups:
            if group.id is not None and group.id in settings:
                self.set_group(group, settings[group.id])
        for session in recovery.sessions:
            if session.group_id in settings:
                self.set_session(session, settings[session.group_id])
        summary = self.manager.recover(recovery)
        self.scheduler.recover(recovery.unfinished_runs)
        return summary

    async def start(self, recovery: RecoveryState) -> RecoverySummary:
        summary = self.load(recovery)
        # Connecting may take long (retries with backoff): it must not hold up start-up, and
        # signals that come before it succeeds are skipped ("... is not connected").
        for broker, adapter in self.adapters.items():
            if broker in self._off:
                log.info("broker_off", broker=broker.value)
                continue
            self._start_connecting(broker, adapter)
        if self.listener is not None:
            self.listener.start()
        self.scheduler.start()
        return summary

    async def stop(self, *, closing: bool = False) -> None:
        """Stop opening pairs, stop taking signals, stop the chains, then close the connections.
        `closing`: the application is closing (Ctrl+C), not the owner stopping trading: a session
        run is left going, so the next start carries it on if its window is still open (D-79)."""
        await self.scheduler.stop(end_run=not closing)
        if self.listener is not None:
            await self.listener.stop()
        await self.manager.stop()
        # A broker still trying to log in is told to stop first (otherwise its retry loop would
        # outlive the engine), then each one closes, with a time limit: Ctrl+C must never hang.
        for task in self._connecting.values():
            task.cancel()
        # All brokers close at the same time, so stopping takes at most one time limit (the stall
        # watchdog ends the process if a stop takes much longer, decision D-80).
        await asyncio.gather(
            *(self._disconnect(broker, adapter) for broker, adapter in self.adapters.items())
        )
        if self._connecting:
            await asyncio.gather(*self._connecting.values(), return_exceptions=True)
            self._connecting.clear()

    @staticmethod
    async def _disconnect(broker: Broker, adapter: BrokerAdapter) -> None:
        try:
            await asyncio.wait_for(adapter.disconnect(), DISCONNECT_TIMEOUT_S)
        except TimeoutError:
            log.warning("broker_disconnect_timeout", broker=broker.value)
        except Exception:
            log.warning("broker_disconnect_failed", broker=broker.value, exc_info=True)
