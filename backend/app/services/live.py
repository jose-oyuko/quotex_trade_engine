"""The live picture of the system, rebuilt from the event stream.

`LiveState` is a projection: it starts empty and is changed only by events, one at a time and in the
order they were published. That is what lets the WebSocket hub promise "a snapshot, then every event
after it, with no gap": the snapshot is this object at one instant, and the events after it are
the ones that have not been applied yet.

It holds only what is still alive (open chains, unsettled trades, the latest connection states and
balance, the controls), so its size does not grow with history. Every event carries a full snapshot
of its record, so applying the same event twice is harmless.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import structlog

from app.domain.enums import (
    ACTIVE_CHAIN_STATUSES,
    UNSETTLED_TRADE_STATUSES,
    AccountType,
)
from app.domain.records import (
    AppSettingRecord,
    BalanceSnapshotRecord,
    ChainRecord,
    TradeRecord,
)
from app.engine.risk import (
    KEY_GROUP_LIMITS_PREFIX,
    KEY_KILL_SWITCH,
    KEY_LIMITS,
    KEY_PAUSED_GROUPS,
    GroupRiskLimits,
    RiskLimits,
    group_id_of,
    parse_group_limits,
    parse_limits,
    parse_paused_groups,
)
from app.events.types import (
    AccountChanged,
    BalanceUpdated,
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    ConnectionChanged,
    Event,
    SettingChanged,
    TradeOpened,
    TradeSettled,
)

log = structlog.get_logger()

CONTROL_KEYS = (KEY_LIMITS, KEY_GROUP_LIMITS_PREFIX, KEY_KILL_SWITCH, KEY_PAUSED_GROUPS)


@dataclass(slots=True, frozen=True)
class ConnectionStatus:
    connected: bool
    detail: str | None
    since: datetime


@dataclass(slots=True)
class Controls:
    """The owner's switches and limits, as stored."""

    kill_switch: bool = False
    paused_groups: frozenset[int] = frozenset()
    limits: RiskLimits = field(default_factory=RiskLimits)
    group_limits: dict[int, GroupRiskLimits] = field(default_factory=dict)


def is_control_setting(key: str) -> bool:
    return key.startswith(CONTROL_KEYS)


class LiveState:
    def __init__(self, settings: Iterable[AppSettingRecord] = ()) -> None:
        self.account_type = AccountType.DEMO  # the adapter starts on demo at every launch (D-15)
        self.connections: dict[str, ConnectionStatus] = {}
        self.balances: dict[AccountType, BalanceSnapshotRecord] = {}
        self.chains: dict[UUID, ChainRecord] = {}
        self.trades: dict[UUID, TradeRecord] = {}
        self.controls = Controls()
        self.last_event_at: datetime | None = None
        for setting in settings:
            self.apply_setting(setting)

    @property
    def balance(self) -> BalanceSnapshotRecord | None:
        """The balance of the account in use now."""
        return self.balances.get(self.account_type)

    def active_chains_of(self, group_id: int) -> int:
        return sum(1 for chain in self.chains.values() if chain.group_id == group_id)

    def apply(self, event: Event) -> None:
        """Change the picture the way the event says. Unknown event types are ignored."""
        self.last_event_at = event.occurred_at
        match event:
            case ChainStarted(chain=chain) | ChainAdvanced(chain=chain) | ChainEnded(chain=chain):
                if chain.status in ACTIVE_CHAIN_STATUSES:
                    self.chains[chain.id] = chain
                else:
                    self.chains.pop(chain.id, None)
            case TradeOpened(trade=trade) | TradeSettled(trade=trade):
                if trade.status in UNSETTLED_TRADE_STATUSES:
                    self.trades[trade.id] = trade
                else:
                    self.trades.pop(trade.id, None)
            case BalanceUpdated(snapshot=snapshot):
                self.balances[snapshot.account_type] = snapshot
            case ConnectionChanged(component=component, connected=connected, detail=detail):
                self.connections[component] = ConnectionStatus(connected, detail, event.occurred_at)
            case AccountChanged(account_type=account_type):
                self.account_type = account_type
            case SettingChanged(setting=setting):
                self.apply_setting(setting)

    def apply_setting(self, setting: AppSettingRecord) -> bool:
        """Returns True if the setting is one of the controls. A stored value that cannot be read
        engages the kill switch in the view too, exactly as the guard does at start-up."""
        if not is_control_setting(setting.key):
            return False
        try:
            self._apply_control(setting)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            log.error("control_setting_unreadable", key=setting.key, exc_info=True)
            self.controls.kill_switch = True
        return True

    def _apply_control(self, setting: AppSettingRecord) -> None:
        key, value = setting.key, setting.value
        if key == KEY_LIMITS:
            self.controls.limits = parse_limits(value)
        elif key.startswith(KEY_GROUP_LIMITS_PREFIX):
            self.controls.group_limits[group_id_of(key)] = parse_group_limits(value)
        elif key == KEY_KILL_SWITCH:
            self.controls.kill_switch = value is True
        elif key == KEY_PAUSED_GROUPS:
            self.controls.paused_groups = parse_paused_groups(value)
