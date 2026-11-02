"""RiskGuard: the limits and the kill switch, consulted synchronously and from memory only.

Every order passes `admit` just before it is sent. `admit` does a handful of comparisons against
numbers kept up to date by the events the engine already produces (trades opening and settling), so
it adds microseconds and never waits (docs/ARCHITECTURE.md section 4). If it says no, the order is
not sent, a `risk.tripped` event says exactly what was blocked and why, and the chain ends.

What "at the limit" means (each is tested just below / at / above):
- max stake, max exposure, max concurrent trades, max chain length, minimum payout: **reaching**
  the limit is allowed, **exceeding** it is blocked (a stake equal to the maximum goes out).
- daily stop-loss and daily profit target: **reaching** the limit blocks (a day that has lost
  exactly the stop-loss amount is over; one that has won exactly the target is over).

The "day" for the daily limits starts at `reset_time` in `reset_timezone` (default 00:00 UTC) and
the totals are per account type, so demo results never count against real limits (D-15).

Controls: the kill switch blocks every new order, follow-ups included; a paused group takes no
new signals but its running chains finish. Both survive a restart (stored as app settings).
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

import structlog

from app.core.clock import Clock
from app.core.errors import DomainError
from app.domain.enums import RESULT_TRADE_STATUSES, AccountType
from app.domain.ids import new_id
from app.domain.records import AppSettingRecord, JsonScalar, RiskEventRecord, TradeRecord
from app.events.bus import EventBus
from app.events.types import RiskTripped, SettingChanged
from app.signals.timezones import InvalidTimezoneError, parse_timezone

log = structlog.get_logger()

KEY_LIMITS = "risk.limits"
KEY_GROUP_LIMITS_PREFIX = "risk.group."
KEY_KILL_SWITCH = "controls.kill_switch"
KEY_PAUSED_GROUPS = "controls.paused_groups"


class RiskConfigError(DomainError, ValueError):
    """A limit has an impossible value (negative, not a number, unknown time zone...)."""


class BlockKind(StrEnum):
    KILL_SWITCH = "kill_switch"
    MAX_STAKE = "max_stake"
    MAX_CONCURRENT_TRADES = "max_concurrent_trades"
    MAX_EXPOSURE = "max_exposure"
    MAX_CHAIN_LENGTH = "max_chain_length"
    MIN_PAYOUT = "min_payout"
    DAILY_STOP_LOSS = "daily_stop_loss"
    DAILY_PROFIT_TARGET = "daily_profit_target"
    GROUP_MAX_STAKE = "group_max_stake"
    GROUP_DAILY_STOP_LOSS = "group_daily_stop_loss"
    GROUP_DAILY_PROFIT_TARGET = "group_daily_profit_target"


def _money(value: Decimal | None, name: str) -> Decimal | None:
    if value is None:
        return None
    if not value.is_finite() or value <= 0:
        raise RiskConfigError(f"{name} must be greater than 0 (or unset), got {value}")
    return value


@dataclass(slots=True, frozen=True)
class RiskLimits:
    """Global limits. `None` means "no limit"."""

    max_stake: Decimal | None = None
    max_concurrent_trades: int | None = None
    max_exposure: Decimal | None = None  # total of the stakes of all open trades
    max_chain_trades: int | None = None  # trades in one chain, the original included
    daily_stop_loss: Decimal | None = None  # net loss of the day that stops trading
    daily_profit_target: Decimal | None = None  # net profit of the day that stops trading
    reset_timezone: str = "UTC"
    reset_time: time = time(0, 0)

    def __post_init__(self) -> None:
        for name in ("max_stake", "max_exposure", "daily_stop_loss", "daily_profit_target"):
            _money(getattr(self, name), name)
        for name in ("max_concurrent_trades", "max_chain_trades"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise RiskConfigError(f"{name} must be at least 1 (or unset), got {value}")
        try:
            parse_timezone(self.reset_timezone)
        except InvalidTimezoneError as exc:
            raise RiskConfigError(str(exc)) from exc


@dataclass(slots=True, frozen=True)
class GroupRiskLimits:
    """Limits of one group, on top of the global ones."""

    max_stake: Decimal | None = None
    daily_stop_loss: Decimal | None = None
    daily_profit_target: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("max_stake", "daily_stop_loss", "daily_profit_target"):
            _money(getattr(self, name), name)


@dataclass(slots=True, frozen=True)
class OrderRequest:
    """What the guard needs to know about an order that is about to be sent."""

    trade_id: UUID
    chain_id: UUID
    group_id: int
    asset: str
    step: int
    stake: Decimal
    account_type: AccountType
    payout_pct: int | None  # None = unknown: the adapter will refuse an unknown asset itself
    min_payout_pct: int = 0


@dataclass(slots=True, frozen=True)
class RiskDecision:
    allowed: bool
    kind: BlockKind | None = None
    message: str | None = None


ALLOWED = RiskDecision(True)


@dataclass(slots=True)
class _Open:
    group_id: int
    stake: Decimal


@dataclass(slots=True, frozen=True)
class _Result:
    """One settled trade's profit, kept for LEDGER_WINDOW so the day's totals can be rebuilt when
    the reset time or zone is edited."""

    at: datetime
    account_type: AccountType
    group_id: int
    profit: Decimal


@dataclass(slots=True)
class _DayTotals:
    start: datetime
    by_group: dict[tuple[AccountType, int], Decimal] = field(default_factory=dict)
    by_account: dict[AccountType, Decimal] = field(default_factory=dict)


# How long settled results are remembered in memory (the same window the start-up reads back).
LEDGER_WINDOW = timedelta(hours=48)


def day_start(now: datetime, tz: tzinfo, reset_time: time) -> datetime:
    """The most recent moment, at or before `now`, at which the clock of `tz` showed `reset_time`
    (as a UTC instant). A `reset_time` inside a daylight-saving gap is not supported."""
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), reset_time, tzinfo=tz)
    if local < start:
        start = datetime.combine(local.date() - timedelta(days=1), reset_time, tzinfo=tz)
    return start.astimezone(UTC)


class RiskGuard:
    def __init__(
        self,
        *,
        clock: Clock,
        bus: EventBus,
        limits: RiskLimits | None = None,
    ) -> None:
        self._clock = clock
        self._bus = bus
        self._limits = limits or RiskLimits()
        self._tz = parse_timezone(self._limits.reset_timezone)
        self._group_limits: dict[int, GroupRiskLimits] = {}
        self._kill_switch = False
        self._paused: set[int] = set()
        self._open: dict[UUID, _Open] = {}
        self._open_stake = Decimal(0)
        self._ledger: deque[_Result] = deque()
        self._day = _DayTotals(day_start(clock.now(), self._tz, self._limits.reset_time))

    # --- configuration ---

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    def set_limits(self, limits: RiskLimits) -> None:
        """Replace the global limits (takes effect for the next order) and remember them. Today's
        result is kept: editing the limits must never reset a stop-loss that has been reached."""
        self._limits = limits
        self._tz = parse_timezone(limits.reset_timezone)
        self._day = self._totals_since(day_start(self._clock.now(), self._tz, limits.reset_time))
        self._save(KEY_LIMITS, _limits_to_json(limits))

    def group_limits(self, group_id: int) -> GroupRiskLimits:
        return self._group_limits.get(group_id, GroupRiskLimits())

    def set_group_limits(self, group_id: int, limits: GroupRiskLimits) -> None:
        self._group_limits[group_id] = limits
        self._save(f"{KEY_GROUP_LIMITS_PREFIX}{group_id}", _group_limits_to_json(limits))

    # --- controls ---

    @property
    def kill_switch(self) -> bool:
        return self._kill_switch

    def engage_kill_switch(self) -> None:
        self._kill_switch = True
        self._save(KEY_KILL_SWITCH, True)

    def release_kill_switch(self) -> None:
        self._kill_switch = False
        self._save(KEY_KILL_SWITCH, False)

    @property
    def paused_groups(self) -> frozenset[int]:
        return frozenset(self._paused)

    def pause_group(self, group_id: int) -> None:
        self._paused.add(group_id)
        self._save_paused()

    def resume_group(self, group_id: int) -> None:
        self._paused.discard(group_id)
        self._save_paused()

    def signal_block_reason(self, group_id: int) -> str | None:
        """Why a new signal of this group must be ignored right now, or None."""
        if self._kill_switch:
            return "kill switch engaged: no new trades"
        if group_id in self._paused:
            return "group is paused"
        return None

    # --- the hot path ---

    def admit(self, request: OrderRequest) -> RiskDecision:
        """Check the order against every limit and, if allowed, reserve it (it counts as open from
        now on). Synchronous, in memory, no awaits: nothing can slip in between the check and the
        reservation."""
        blocked = self._check(request)
        if blocked is not None:
            self._trip(blocked, request)
            return blocked
        self._open[request.trade_id] = _Open(request.group_id, request.stake)
        self._open_stake += request.stake
        return ALLOWED

    def release(self, trade_id: UUID) -> None:
        """The order was not placed, or its result will never be known: stop counting it open."""
        reserved = self._open.pop(trade_id, None)
        if reserved is not None:
            self._open_stake -= reserved.stake

    def settled(self, trade: TradeRecord) -> None:
        """A trade with a known result: free its reservation and book its profit for the day."""
        self.release(trade.id)
        if trade.status in RESULT_TRADE_STATUSES and trade.profit is not None:
            self._book(trade.account_type, trade.group_id, trade.profit, self._clock.now())

    @property
    def open_trades(self) -> int:
        return len(self._open)

    @property
    def open_exposure(self) -> Decimal:
        return self._open_stake

    def day_pnl(self, account_type: AccountType, group_id: int | None = None) -> Decimal:
        """Net result of the current day (positive = profit)."""
        self._roll(self._clock.now())
        if group_id is None:
            return self._day.by_account.get(account_type, Decimal(0))
        return self._day.by_group.get((account_type, group_id), Decimal(0))

    @property
    def current_day_start(self) -> datetime:
        self._roll(self._clock.now())
        return self._day.start

    # --- start-up ---

    def load(
        self,
        settings: Iterable[AppSettingRecord],
        recent_settled_trades: Iterable[TradeRecord],
    ) -> None:
        """Restore what was stored: limits, the kill switch, paused groups, and today's totals."""
        for setting in settings:
            try:
                self._restore(setting)
            except (RiskConfigError, ValueError, TypeError, KeyError, InvalidOperation):
                # A damaged limit must not stop start-up, and must not silently become "no limit":
                # the safe reading of a setting we cannot read is to stop trading.
                log.error("risk_setting_unreadable", key=setting.key, exc_info=True)
                self._kill_switch = True
        now = self._clock.now()
        self._roll(now)
        for trade in recent_settled_trades:
            if trade.settled_at is not None and trade.profit is not None:
                self._book(trade.account_type, trade.group_id, trade.profit, trade.settled_at)

    def _restore(self, setting: AppSettingRecord) -> None:
        key, value = setting.key, setting.value
        if key == KEY_LIMITS and isinstance(value, str):
            self._limits = _limits_from_json(value)
            self._tz = parse_timezone(self._limits.reset_timezone)
            self._day = self._totals_since(
                day_start(self._clock.now(), self._tz, self._limits.reset_time)
            )
        elif key.startswith(KEY_GROUP_LIMITS_PREFIX) and isinstance(value, str):
            self._group_limits[group_id_of(key)] = _group_limits_from_json(value)
        elif key == KEY_KILL_SWITCH:
            self._kill_switch = value is True
        elif key == KEY_PAUSED_GROUPS and isinstance(value, str):
            self._paused = set(parse_paused_groups(value))

    # --- internals ---

    def _roll(self, now: datetime) -> None:
        start = day_start(now, self._tz, self._limits.reset_time)
        if start != self._day.start:
            self._day = self._totals_since(start)

    def _totals_since(self, start: datetime) -> _DayTotals:
        """The day that began at `start`, rebuilt from the remembered results."""
        totals = _DayTotals(start)
        for result in self._ledger:
            if result.at >= start:
                _add(totals, result)
        return totals

    def _book(self, account: AccountType, group_id: int, profit: Decimal, at: datetime) -> None:
        """Remember a settled result (made at `at`); it joins today's totals if it is today's."""
        self._roll(self._clock.now())
        result = _Result(at, account, group_id, profit)
        self._ledger.append(result)
        cutoff = self._clock.now() - LEDGER_WINDOW
        while self._ledger and self._ledger[0].at < cutoff:
            self._ledger.popleft()
        if at >= self._day.start:
            _add(self._day, result)

    def _check(self, r: OrderRequest) -> RiskDecision | None:
        limits, group = self._limits, self.group_limits(r.group_id)
        if self._kill_switch:
            return _block(BlockKind.KILL_SWITCH, "kill switch engaged: no new orders")
        if limits.max_chain_trades is not None and r.step + 1 > limits.max_chain_trades:
            return _block(
                BlockKind.MAX_CHAIN_LENGTH,
                f"trade {r.step + 1} of a chain exceeds the limit of {limits.max_chain_trades}",
            )
        if r.step == 0 and r.payout_pct is not None and r.payout_pct < r.min_payout_pct:
            return _block(
                BlockKind.MIN_PAYOUT,
                f"payout {r.payout_pct}% on {r.asset} is below the group's minimum "
                f"{r.min_payout_pct}%",
            )
        if limits.max_stake is not None and r.stake > limits.max_stake:
            return _block(
                BlockKind.MAX_STAKE, f"stake {r.stake} exceeds the maximum {limits.max_stake}"
            )
        if group.max_stake is not None and r.stake > group.max_stake:
            return _block(
                BlockKind.GROUP_MAX_STAKE,
                f"stake {r.stake} exceeds this group's maximum {group.max_stake}",
            )
        self._roll(self._clock.now())
        account_pnl = self._day.by_account.get(r.account_type, Decimal(0))
        group_pnl = self._day.by_group.get((r.account_type, r.group_id), Decimal(0))
        if limits.daily_stop_loss is not None and account_pnl <= -limits.daily_stop_loss:
            return _block(
                BlockKind.DAILY_STOP_LOSS,
                f"the day's result {account_pnl} has reached the stop-loss "
                f"-{limits.daily_stop_loss}",
            )
        if group.daily_stop_loss is not None and group_pnl <= -group.daily_stop_loss:
            return _block(
                BlockKind.GROUP_DAILY_STOP_LOSS,
                f"this group's result today {group_pnl} has reached its stop-loss "
                f"-{group.daily_stop_loss}",
            )
        if limits.daily_profit_target is not None and account_pnl >= limits.daily_profit_target:
            return _block(
                BlockKind.DAILY_PROFIT_TARGET,
                f"the day's result {account_pnl} has reached the profit target "
                f"{limits.daily_profit_target}",
            )
        if group.daily_profit_target is not None and group_pnl >= group.daily_profit_target:
            return _block(
                BlockKind.GROUP_DAILY_PROFIT_TARGET,
                f"this group's result today {group_pnl} has reached its profit target "
                f"{group.daily_profit_target}",
            )
        if (
            limits.max_concurrent_trades is not None
            and len(self._open) + 1 > limits.max_concurrent_trades
        ):
            return _block(
                BlockKind.MAX_CONCURRENT_TRADES,
                f"{len(self._open)} trades are already open; the limit is "
                f"{limits.max_concurrent_trades}",
            )
        if limits.max_exposure is not None and self._open_stake + r.stake > limits.max_exposure:
            return _block(
                BlockKind.MAX_EXPOSURE,
                f"open stakes {self._open_stake} + {r.stake} would exceed the exposure limit "
                f"{limits.max_exposure}",
            )
        return None

    def _trip(self, decision: RiskDecision, r: OrderRequest) -> None:
        now = self._clock.now()
        details: Mapping[str, JsonScalar] = {
            "asset": r.asset,
            "step": r.step,
            "stake": str(r.stake),
            "chain_id": str(r.chain_id),
            "blocked": "order",
        }
        self._bus.publish(
            RiskTripped(
                occurred_at=now,
                risk_event=RiskEventRecord(
                    id=new_id(),
                    occurred_at=now,
                    kind=decision.kind.value if decision.kind else "blocked",
                    message=f"order not sent: {decision.message}",
                    group_id=r.group_id,
                    details=details,
                ),
            )
        )

    def _save(self, key: str, value: JsonScalar) -> None:
        now = self._clock.now()
        self._bus.publish(
            SettingChanged(
                occurred_at=now, setting=AppSettingRecord(key=key, value=value, updated_at=now)
            )
        )

    def _save_paused(self) -> None:
        self._save(KEY_PAUSED_GROUPS, json.dumps(sorted(self._paused)))


def _add(totals: _DayTotals, result: _Result) -> None:
    key = (result.account_type, result.group_id)
    totals.by_group[key] = totals.by_group.get(key, Decimal(0)) + result.profit
    totals.by_account[result.account_type] = (
        totals.by_account.get(result.account_type, Decimal(0)) + result.profit
    )


def _block(kind: BlockKind, message: str) -> RiskDecision:
    return RiskDecision(False, kind, message)


# --- (de)serialisation of the limits for the app_settings table ---
# The public helpers below let the API store and read limits without the engine running (limits
# must be settable *before* the engine is first enabled), using the very same format.


def limits_setting(limits: RiskLimits, now: datetime) -> AppSettingRecord:
    return AppSettingRecord(key=KEY_LIMITS, value=_limits_to_json(limits), updated_at=now)


def group_limits_setting(group_id: int, limits: GroupRiskLimits, now: datetime) -> AppSettingRecord:
    return AppSettingRecord(
        key=f"{KEY_GROUP_LIMITS_PREFIX}{group_id}",
        value=_group_limits_to_json(limits),
        updated_at=now,
    )


def parse_limits(value: JsonScalar) -> RiskLimits:
    """Raises `RiskConfigError`, `ValueError`, `KeyError` or `TypeError` if the text is damaged."""
    if not isinstance(value, str):
        raise TypeError("the stored limits are not text")
    return _limits_from_json(value)


def parse_group_limits(value: JsonScalar) -> GroupRiskLimits:
    if not isinstance(value, str):
        raise TypeError("the stored group limits are not text")
    return _group_limits_from_json(value)


def parse_paused_groups(value: JsonScalar) -> frozenset[int]:
    if not isinstance(value, str):
        raise TypeError("the stored list of paused groups is not text")
    return frozenset(int(part) for part in json.loads(value))


def group_id_of(key: str) -> int:
    """The group id in a `risk.group.<id>` setting key."""
    return int(key.removeprefix(KEY_GROUP_LIMITS_PREFIX))


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _limits_to_json(limits: RiskLimits) -> str:
    return json.dumps(
        {
            "max_stake": _str_or_none(limits.max_stake),
            "max_concurrent_trades": limits.max_concurrent_trades,
            "max_exposure": _str_or_none(limits.max_exposure),
            "max_chain_trades": limits.max_chain_trades,
            "daily_stop_loss": _str_or_none(limits.daily_stop_loss),
            "daily_profit_target": _str_or_none(limits.daily_profit_target),
            "reset_timezone": limits.reset_timezone,
            "reset_time": limits.reset_time.strftime("%H:%M"),
        }
    )


def _limits_from_json(text: str) -> RiskLimits:
    data = json.loads(text)
    hour, minute = str(data["reset_time"]).split(":")
    return RiskLimits(
        max_stake=_decimal_or_none(data["max_stake"]),
        max_concurrent_trades=data["max_concurrent_trades"],
        max_exposure=_decimal_or_none(data["max_exposure"]),
        max_chain_trades=data["max_chain_trades"],
        daily_stop_loss=_decimal_or_none(data["daily_stop_loss"]),
        daily_profit_target=_decimal_or_none(data["daily_profit_target"]),
        reset_timezone=data["reset_timezone"],
        reset_time=time(int(hour), int(minute)),
    )


def _group_limits_to_json(limits: GroupRiskLimits) -> str:
    return json.dumps(
        {
            "max_stake": _str_or_none(limits.max_stake),
            "daily_stop_loss": _str_or_none(limits.daily_stop_loss),
            "daily_profit_target": _str_or_none(limits.daily_profit_target),
        }
    )


def _group_limits_from_json(text: str) -> GroupRiskLimits:
    data = json.loads(text)
    return GroupRiskLimits(
        max_stake=_decimal_or_none(data["max_stake"]),
        daily_stop_loss=_decimal_or_none(data["daily_stop_loss"]),
        daily_profit_target=_decimal_or_none(data["daily_profit_target"]),
    )


def _str_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
