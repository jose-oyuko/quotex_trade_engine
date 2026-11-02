"""LiveState: the live picture is built from events alone, and holds only what is still alive."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.domain.enums import AccountType, ChainStatus, TradeStatus
from app.domain.ids import new_id
from app.domain.records import AppSettingRecord
from app.engine.risk import (
    KEY_KILL_SWITCH,
    KEY_LIMITS,
    KEY_PAUSED_GROUPS,
    GroupRiskLimits,
    RiskLimits,
    group_limits_setting,
    limits_setting,
)
from app.events.types import (
    AccountChanged,
    BalanceUpdated,
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    ConnectionChanged,
    SettingChanged,
    TradeOpened,
    TradeSettled,
)
from app.services.live import LiveState, is_control_setting
from tests.factories import NOW, make_balance, make_chain, make_trade

D = Decimal


def setting(key: str, value: object) -> AppSettingRecord:
    return AppSettingRecord(key=key, value=value, updated_at=NOW)  # type: ignore[arg-type]


def test_a_chain_is_live_from_its_start_until_it_ends() -> None:
    live = LiveState()
    chain = make_chain(1, status=ChainStatus.PENDING)
    live.apply(ChainStarted(occurred_at=NOW, chain=chain))
    assert live.chains == {chain.id: chain}
    assert live.active_chains_of(1) == 1 and live.active_chains_of(2) == 0

    advanced = replace(chain, status=ChainStatus.OPEN, step=1)
    live.apply(ChainAdvanced(occurred_at=NOW, chain=advanced))
    assert live.chains[chain.id] == advanced

    live.apply(ChainEnded(occurred_at=NOW, chain=replace(chain, status=ChainStatus.COMPLETED)))
    assert live.chains == {}


def test_a_chain_that_is_already_over_is_never_shown_as_live() -> None:
    live = LiveState()
    live.apply(ChainEnded(occurred_at=NOW, chain=make_chain(1, status=ChainStatus.UNKNOWN)))
    assert live.chains == {}


def test_a_trade_is_live_until_it_settles_whatever_the_result() -> None:
    live = LiveState()
    for final in (TradeStatus.WON, TradeStatus.LOST, TradeStatus.FAILED, TradeStatus.UNKNOWN):
        trade = make_trade(new_id(), 1, status=TradeStatus.PENDING)
        live.apply(TradeOpened(occurred_at=NOW, trade=trade))
        live.apply(TradeOpened(occurred_at=NOW, trade=replace(trade, status=TradeStatus.OPEN)))
        assert len(live.trades) == 1
        live.apply(TradeSettled(occurred_at=NOW, trade=replace(trade, status=final)))
        assert live.trades == {}, final


def test_applying_the_same_event_twice_changes_nothing() -> None:
    live = LiveState()
    event = ChainStarted(occurred_at=NOW, chain=make_chain(1))
    live.apply(event)
    live.apply(event)
    assert len(live.chains) == 1


def test_connections_balance_and_account_follow_their_events() -> None:
    live = LiveState()
    assert live.account_type is AccountType.DEMO and live.balance is None
    live.apply(ConnectionChanged(occurred_at=NOW, component="quotex", connected=True, detail="up"))
    live.apply(ConnectionChanged(occurred_at=NOW, component="telegram", connected=False))
    assert live.connections["quotex"].connected is True
    assert live.connections["quotex"].detail == "up" and live.connections["quotex"].since == NOW
    assert live.connections["telegram"].connected is False

    live.apply(BalanceUpdated(occurred_at=NOW, snapshot=make_balance(balance=D("10"))))
    live.apply(
        BalanceUpdated(
            occurred_at=NOW, snapshot=make_balance(account_type=AccountType.REAL, balance=D("99"))
        )
    )
    assert live.balance is not None and live.balance.balance == D("10")  # the account in use
    live.apply(AccountChanged(occurred_at=NOW, account_type=AccountType.REAL))
    assert live.balance is not None and live.balance.balance == D("99")
    assert live.last_event_at == NOW


def test_the_controls_start_from_the_stored_settings_and_follow_changes() -> None:
    limits = RiskLimits(max_stake=D("5.00"), daily_stop_loss=D("20"))
    live = LiveState(
        [
            limits_setting(limits, NOW),
            group_limits_setting(3, GroupRiskLimits(max_stake=D("1")), NOW),
            setting(KEY_KILL_SWITCH, True),
            setting(KEY_PAUSED_GROUPS, "[2, 3]"),
        ]
    )
    assert live.controls.limits == limits
    assert live.controls.group_limits == {3: GroupRiskLimits(max_stake=D("1"))}
    assert live.controls.kill_switch is True and live.controls.paused_groups == {2, 3}

    live.apply(SettingChanged(occurred_at=NOW, setting=setting(KEY_KILL_SWITCH, False)))
    live.apply(SettingChanged(occurred_at=NOW, setting=setting(KEY_PAUSED_GROUPS, "[]")))
    assert live.controls.kill_switch is False and live.controls.paused_groups == frozenset()


def test_a_stored_control_that_cannot_be_read_engages_the_kill_switch_in_the_view_too() -> None:
    for bad in (setting(KEY_LIMITS, "{not json"), setting(KEY_LIMITS, '{"max_stake": "1"}')):
        live = LiveState([bad])
        assert live.controls.kill_switch is True, bad.value
    assert LiveState([setting(KEY_PAUSED_GROUPS, "nonsense")]).controls.kill_switch is True


def test_settings_that_are_not_controls_are_ignored() -> None:
    live = LiveState()
    assert live.apply_setting(setting("something.else", 1)) is False
    assert live.apply_setting(setting(KEY_KILL_SWITCH, True)) is True
    assert is_control_setting("risk.group.7") and not is_control_setting("ui.theme")
