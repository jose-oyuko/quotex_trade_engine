"""RiskGuard: each limit just below, at and above its threshold; the daily reset; persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

import pytest

from app.domain.enums import AccountType, TradeStatus
from app.domain.ids import new_id
from app.domain.records import AppSettingRecord
from app.engine.risk import (
    BlockKind,
    GroupRiskLimits,
    OrderRequest,
    RiskConfigError,
    RiskGuard,
    RiskLimits,
    day_start,
)
from app.events.bus import EventBus
from app.events.types import RiskTripped, SettingChanged
from tests.factories import make_trade
from tests.signal_support import T0, ManualClock

D = Decimal
GROUP = 1


def make_guard(limits: RiskLimits | None = None, clock: ManualClock | None = None) -> RiskGuard:
    return RiskGuard(clock=clock or ManualClock(), bus=EventBus(), limits=limits)


def request(
    stake: str = "1.00",
    *,
    step: int = 0,
    group: int = GROUP,
    payout: int | None = 85,
    min_payout: int = 0,
    account: AccountType = AccountType.DEMO,
) -> OrderRequest:
    return OrderRequest(
        trade_id=new_id(),
        chain_id=new_id(),
        group_id=group,
        asset="EURUSD",
        step=step,
        stake=D(stake),
        account_type=account,
        payout_pct=payout,
        min_payout_pct=min_payout,
    )


def result(profit: str, *, group: int = GROUP, account: AccountType = AccountType.DEMO, at=None):  # type: ignore[no-untyped-def]
    return make_trade(
        new_id(),
        group,
        status=TradeStatus.WON if D(profit) > 0 else TradeStatus.LOST,
        profit=D(profit),
        settled_at=at or T0,
        account_type=account,
    )


def book(guard: RiskGuard, profit: str, **kwargs):  # type: ignore[no-untyped-def]
    guard.settled(result(profit, **kwargs))


def blocked_kind(guard: RiskGuard, req: OrderRequest) -> BlockKind | None:
    decision = guard.admit(req)
    return decision.kind if not decision.allowed else None


# --- no limits, no blocks ---


def test_without_limits_everything_is_allowed() -> None:
    guard = make_guard()
    assert guard.admit(request("1000000.00", step=50)).allowed


# --- max stake: at the limit goes out, above is blocked ---


@pytest.mark.parametrize(("stake", "allowed"), [("9.99", True), ("10.00", True), ("10.01", False)])
def test_max_stake(stake: str, allowed: bool) -> None:
    guard = make_guard(RiskLimits(max_stake=D("10.00")))
    decision = guard.admit(request(stake))
    assert decision.allowed is allowed
    if not allowed:
        assert decision.kind is BlockKind.MAX_STAKE
        assert decision.message is not None and "10.01" in decision.message


@pytest.mark.parametrize(("stake", "allowed"), [("4.99", True), ("5.00", True), ("5.01", False)])
def test_group_max_stake_only_applies_to_that_group(stake: str, allowed: bool) -> None:
    guard = make_guard()
    guard.set_group_limits(GROUP, GroupRiskLimits(max_stake=D("5.00")))
    assert guard.admit(request(stake)).allowed is allowed
    assert guard.admit(request("50.00", group=2)).allowed  # another group is unaffected


# --- max concurrent trades: the 3rd of 3 goes out, the 4th does not ---


@pytest.mark.parametrize(("already_open", "allowed"), [(1, True), (2, True), (3, False)])
def test_max_concurrent_trades(already_open: int, allowed: bool) -> None:
    guard = make_guard(RiskLimits(max_concurrent_trades=3))
    for _ in range(already_open):
        assert guard.admit(request()).allowed
    decision = guard.admit(request())
    assert decision.allowed is allowed
    if not allowed:
        assert decision.kind is BlockKind.MAX_CONCURRENT_TRADES


def test_a_settled_trade_makes_room_again() -> None:
    guard = make_guard(RiskLimits(max_concurrent_trades=1))
    first = request()
    assert guard.admit(first).allowed
    assert not guard.admit(request()).allowed
    guard.settled(make_trade(first.chain_id, GROUP, id=first.trade_id, status=TradeStatus.LOST))
    assert guard.open_trades == 0
    assert guard.admit(request()).allowed


# --- max exposure: open stakes may add up to the cap, not beyond ---


@pytest.mark.parametrize(("second", "allowed"), [("5.99", True), ("6.00", True), ("6.01", False)])
def test_max_exposure(second: str, allowed: bool) -> None:
    guard = make_guard(RiskLimits(max_exposure=D("10.00")))
    assert guard.admit(request("4.00")).allowed
    decision = guard.admit(request(second))
    assert decision.allowed is allowed
    assert guard.open_exposure == (D("4.00") + D(second) if allowed else D("4.00"))
    if not allowed:
        assert decision.kind is BlockKind.MAX_EXPOSURE


def test_released_stakes_leave_the_exposure() -> None:
    guard = make_guard(RiskLimits(max_exposure=D("5.00")))
    first = request("5.00")
    assert guard.admit(first).allowed
    assert not guard.admit(request("0.01")).allowed
    guard.release(first.trade_id)  # the order was refused downstream
    assert guard.open_exposure == D("0")
    assert guard.admit(request("5.00")).allowed


def test_releasing_twice_or_an_unknown_trade_changes_nothing() -> None:
    guard = make_guard()
    first = request("2.00")
    guard.admit(first)
    guard.release(first.trade_id)
    guard.release(first.trade_id)
    guard.release(new_id())
    assert (guard.open_trades, guard.open_exposure) == (0, D("0"))


# --- max chain length ---


@pytest.mark.parametrize(("step", "allowed"), [(1, True), (2, True), (3, False)])
def test_max_chain_length_counts_the_original_trade(step: int, allowed: bool) -> None:
    guard = make_guard(RiskLimits(max_chain_trades=3))  # trades at step 0, 1, 2 may go out
    decision = guard.admit(request(step=step))
    assert decision.allowed is allowed
    if not allowed:
        assert decision.kind is BlockKind.MAX_CHAIN_LENGTH


# --- minimum payout: only the signal's own trade is filtered ---


@pytest.mark.parametrize(("payout", "allowed"), [(81, True), (80, True), (79, False)])
def test_min_payout(payout: int, allowed: bool) -> None:
    guard = make_guard()
    decision = guard.admit(request(payout=payout, min_payout=80))
    assert decision.allowed is allowed
    if not allowed:
        assert decision.kind is BlockKind.MIN_PAYOUT


def test_min_payout_does_not_cut_a_running_chain_short() -> None:
    assert make_guard().admit(request(step=1, payout=70, min_payout=80)).allowed


def test_an_unknown_payout_is_not_a_reason_to_block() -> None:
    assert make_guard().admit(request(payout=None, min_payout=80)).allowed


# --- daily stop-loss and profit target: reaching the limit ends the day ---


@pytest.mark.parametrize(
    ("net", "allowed"), [("-9.99", True), ("-10.00", False), ("-10.01", False), ("0", True)]
)
def test_daily_stop_loss(net: str, allowed: bool) -> None:
    guard = make_guard(RiskLimits(daily_stop_loss=D("10.00")))
    book(guard, net)
    decision = guard.admit(request())
    assert decision.allowed is allowed
    if not allowed:
        assert decision.kind is BlockKind.DAILY_STOP_LOSS


@pytest.mark.parametrize(
    ("net", "allowed"), [("9.99", True), ("10.00", False), ("10.01", False), ("-50", True)]
)
def test_daily_profit_target(net: str, allowed: bool) -> None:
    guard = make_guard(RiskLimits(daily_profit_target=D("10.00")))
    book(guard, net)
    decision = guard.admit(request())
    assert decision.allowed is allowed
    if not allowed:
        assert decision.kind is BlockKind.DAILY_PROFIT_TARGET


@pytest.mark.parametrize("net", ["-4.99", "-5.00", "-5.01"])
def test_group_daily_stop_loss_counts_only_that_group(net: str) -> None:
    guard = make_guard()
    guard.set_group_limits(GROUP, GroupRiskLimits(daily_stop_loss=D("5.00")))
    book(guard, net)
    book(guard, "-100", group=2)  # another group's losses are not this group's
    expected_allowed = D(net) > D("-5.00")
    assert guard.admit(request()).allowed is expected_allowed
    assert guard.admit(request(group=3)).allowed


@pytest.mark.parametrize("net", ["4.99", "5.00", "5.01"])
def test_group_daily_profit_target_counts_only_that_group(net: str) -> None:
    guard = make_guard()
    guard.set_group_limits(GROUP, GroupRiskLimits(daily_profit_target=D("5.00")))
    book(guard, net)
    assert guard.admit(request()).allowed is (D(net) < D("5.00"))
    assert guard.admit(request(group=2)).allowed


def test_wins_and_losses_net_off_within_the_day() -> None:
    guard = make_guard(RiskLimits(daily_stop_loss=D("10.00")))
    book(guard, "-9")
    book(guard, "4")
    book(guard, "-4")
    assert guard.day_pnl(AccountType.DEMO) == D("-9")
    assert guard.admit(request()).allowed
    book(guard, "-1")
    assert not guard.admit(request()).allowed


def test_demo_results_never_count_against_real_limits() -> None:
    guard = make_guard(RiskLimits(daily_stop_loss=D("10.00")))
    book(guard, "-50", account=AccountType.DEMO)
    assert not guard.admit(request(account=AccountType.DEMO)).allowed
    assert guard.admit(request(account=AccountType.REAL)).allowed


def test_trades_without_a_known_result_do_not_change_the_day() -> None:
    guard = make_guard(RiskLimits(daily_stop_loss=D("1.00")))
    guard.settled(make_trade(new_id(), GROUP, status=TradeStatus.UNKNOWN, profit=None))
    guard.settled(make_trade(new_id(), GROUP, status=TradeStatus.FAILED, profit=None))
    assert guard.day_pnl(AccountType.DEMO) == D("0")


# --- the kill switch and pausing ---


def test_the_kill_switch_blocks_every_order_including_follow_ups() -> None:
    guard = make_guard()
    guard.engage_kill_switch()
    for step in (0, 1, 5):
        decision = guard.admit(request(step=step))
        assert not decision.allowed and decision.kind is BlockKind.KILL_SWITCH
    assert guard.open_trades == 0
    guard.release_kill_switch()
    assert guard.admit(request()).allowed


def test_the_kill_switch_is_checked_before_everything_else() -> None:
    guard = make_guard(RiskLimits(max_stake=D("1.00")))
    guard.engage_kill_switch()
    assert blocked_kind(guard, request("500.00")) is BlockKind.KILL_SWITCH


def test_signal_gate_reports_the_kill_switch_and_paused_groups() -> None:
    guard = make_guard()
    assert guard.signal_block_reason(GROUP) is None
    guard.pause_group(GROUP)
    assert guard.signal_block_reason(GROUP) == "group is paused"
    assert guard.signal_block_reason(2) is None
    guard.resume_group(GROUP)
    assert guard.signal_block_reason(GROUP) is None
    guard.engage_kill_switch()
    reason = guard.signal_block_reason(2)
    assert reason is not None and "kill switch" in reason


def test_pausing_does_not_block_orders_of_chains_already_running() -> None:
    guard = make_guard()
    guard.pause_group(GROUP)
    assert guard.admit(request(step=1)).allowed


# --- what a block says ---


def test_a_blocked_order_publishes_a_risk_event_that_says_what_was_blocked() -> None:
    bus = EventBus()
    feed = bus.subscribe(RiskTripped)
    guard = RiskGuard(clock=ManualClock(), bus=bus, limits=RiskLimits(max_stake=D("2.00")))
    req = request("3.00", step=2)
    assert not guard.admit(req).allowed
    event = feed.get_nowait()
    assert isinstance(event, RiskTripped)
    record = event.risk_event
    assert record.kind == "max_stake" and record.group_id == GROUP
    assert record.message.startswith("order not sent:") and "3.00" in record.message
    assert record.details == {
        "asset": "EURUSD",
        "step": 2,
        "stake": "3.00",
        "chain_id": str(req.chain_id),
        "blocked": "order",
    }
    assert feed.get_nowait() is None


def test_an_allowed_order_publishes_nothing() -> None:
    bus = EventBus()
    feed = bus.subscribe(RiskTripped)
    RiskGuard(clock=ManualClock(), bus=bus).admit(request())
    assert feed.get_nowait() is None


# --- the day: when the daily limits reset ---


def test_the_day_starts_at_midnight_utc_by_default() -> None:
    assert day_start(datetime(2026, 11, 1, 23, 59, 59, tzinfo=UTC), UTC, time(0, 0)) == datetime(
        2026, 11, 1, tzinfo=UTC
    )
    assert day_start(datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC), UTC, time(0, 0)) == datetime(
        2026, 11, 2, tzinfo=UTC
    )


def test_the_day_can_start_at_another_time_in_another_zone() -> None:
    """06:00 in UTC-3 is 09:00 UTC. At 08:59 UTC the day that began yesterday is still running."""
    tz = ZoneInfo("America/Sao_Paulo")  # UTC-3 all year since 2019
    start = lambda h, m: day_start(datetime(2026, 11, 2, h, m, tzinfo=UTC), tz, time(6, 0))  # noqa: E731
    assert start(8, 59) == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    assert start(9, 0) == datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def test_the_day_follows_daylight_saving_in_the_chosen_zone() -> None:
    ny = ZoneInfo("America/New_York")
    midnight = time(0, 0)
    before = day_start(datetime(2026, 3, 7, 12, tzinfo=UTC), ny, midnight)  # EST: midnight = 05:00Z
    after = day_start(datetime(2026, 3, 9, 12, tzinfo=UTC), ny, midnight)  # EDT: midnight = 04:00Z
    assert before == datetime(2026, 3, 7, 5, tzinfo=UTC)
    assert after == datetime(2026, 3, 9, 4, tzinfo=UTC)


def test_the_daily_totals_reset_at_the_boundary_and_not_a_second_before() -> None:
    clock = ManualClock(datetime(2026, 11, 1, 23, 59, 58, tzinfo=UTC))
    guard = make_guard(RiskLimits(daily_stop_loss=D("10.00")), clock)
    book(guard, "-10")
    assert not guard.admit(request()).allowed
    clock.set(datetime(2026, 11, 1, 23, 59, 59, tzinfo=UTC))
    assert not guard.admit(request()).allowed  # one second before the reset: still blocked
    clock.set(datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC))
    assert guard.admit(request()).allowed  # the new day starts from zero
    assert guard.day_pnl(AccountType.DEMO) == D("0")
    assert guard.current_day_start == datetime(2026, 11, 2, tzinfo=UTC)


def test_the_reset_follows_the_configured_zone_and_time() -> None:
    limits = RiskLimits(
        daily_stop_loss=D("10.00"), reset_timezone="UTC-3", reset_time=time(6, 0)
    )  # the day turns over at 09:00 UTC
    clock = ManualClock(datetime(2026, 11, 2, 8, 59, tzinfo=UTC))
    guard = make_guard(limits, clock)
    book(guard, "-10")
    assert not guard.admit(request()).allowed
    clock.set(datetime(2026, 11, 2, 9, 0, tzinfo=UTC))
    assert guard.admit(request()).allowed


def test_editing_the_limits_does_not_reset_the_days_result() -> None:
    guard = make_guard(RiskLimits(daily_stop_loss=D("10.00")))
    book(guard, "-10")
    assert not guard.admit(request()).allowed
    guard.set_limits(RiskLimits(daily_stop_loss=D("10.00"), max_stake=D("5.00")))
    assert guard.day_pnl(AccountType.DEMO) == D("-10")
    assert blocked_kind(guard, request()) is BlockKind.DAILY_STOP_LOSS  # re-saving is no way out


def test_moving_the_reset_time_rebuilds_the_day_from_the_results_since() -> None:
    clock = ManualClock(datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    guard = make_guard(RiskLimits(), clock)
    book(guard, "-4")  # settled at 12:00
    clock.set(datetime(2026, 11, 1, 13, 0, tzinfo=UTC))
    book(guard, "-3")  # settled at 13:00
    assert guard.day_pnl(AccountType.DEMO) == D("-7")
    guard.set_limits(RiskLimits(reset_time=time(12, 30)))  # the day now began at 12:30
    assert guard.day_pnl(AccountType.DEMO) == D("-3")
    guard.set_limits(RiskLimits())  # and back to midnight: both results belong to the day again
    assert guard.day_pnl(AccountType.DEMO) == D("-7")


def test_group_totals_reset_with_the_day_too() -> None:
    clock = ManualClock(datetime(2026, 11, 1, 23, 0, tzinfo=UTC))
    guard = make_guard(None, clock)
    guard.set_group_limits(GROUP, GroupRiskLimits(daily_stop_loss=D("3.00")))
    book(guard, "-3")
    assert not guard.admit(request()).allowed
    clock.advance(3600)
    assert guard.admit(request()).allowed


# --- configuration is validated ---


@pytest.mark.parametrize(
    "bad",
    [
        {"max_stake": D("0")},
        {"max_stake": D("-1")},
        {"max_exposure": D("NaN")},
        {"daily_stop_loss": D("-5")},
        {"max_concurrent_trades": 0},
        {"max_chain_trades": 0},
        {"reset_timezone": "Mars/Base"},
    ],
)
def test_impossible_limits_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(RiskConfigError):
        RiskLimits(**bad)  # type: ignore[arg-type]


def test_impossible_group_limits_are_refused() -> None:
    with pytest.raises(RiskConfigError):
        GroupRiskLimits(daily_stop_loss=D("0"))


# --- persistence: limits and controls survive a restart ---


def saved(bus: EventBus, feed) -> list[AppSettingRecord]:  # type: ignore[no-untyped-def]
    found = []
    while (event := feed.get_nowait()) is not None:
        assert isinstance(event, SettingChanged)
        found.append(event.setting)
    return found


def test_limits_and_controls_are_published_for_storage_and_restored() -> None:
    bus = EventBus()
    feed = bus.subscribe(SettingChanged)
    original = RiskGuard(clock=ManualClock(), bus=bus)
    limits = RiskLimits(
        max_stake=D("10.00"),
        max_concurrent_trades=4,
        max_exposure=D("25.50"),
        max_chain_trades=5,
        daily_stop_loss=D("30"),
        daily_profit_target=D("60"),
        reset_timezone="Africa/Nairobi",
        reset_time=time(4, 30),
    )
    original.set_limits(limits)
    original.set_group_limits(7, GroupRiskLimits(D("2.00"), D("5"), D("9")))
    original.pause_group(3)
    original.pause_group(1)
    original.engage_kill_switch()
    settings = saved(bus, feed)
    assert {s.key for s in settings} == {
        "risk.limits",
        "risk.group.7",
        "controls.paused_groups",
        "controls.kill_switch",
    }

    restored = make_guard()
    stored = {s.key: s for s in settings}  # the database keeps the last write per key
    restored.load(stored.values(), [])
    assert restored.limits == limits
    assert restored.group_limits(7) == GroupRiskLimits(D("2.00"), D("5"), D("9"))
    assert restored.paused_groups == {1, 3}
    assert restored.kill_switch is True


def test_releasing_the_kill_switch_is_stored_too() -> None:
    bus = EventBus()
    feed = bus.subscribe(SettingChanged)
    guard = RiskGuard(clock=ManualClock(), bus=bus)
    guard.engage_kill_switch()
    guard.release_kill_switch()
    values = [s.value for s in saved(bus, feed)]
    assert values == [True, False]
    restored = make_guard()
    restored.load([AppSettingRecord("controls.kill_switch", False, T0)], [])
    assert restored.kill_switch is False


@pytest.mark.parametrize(
    "broken",
    [
        AppSettingRecord("risk.limits", "{not json", T0),
        AppSettingRecord("risk.limits", json.dumps({"max_stake": "abc"}), T0),
        AppSettingRecord("risk.group.2", "[]", T0),
        AppSettingRecord("controls.paused_groups", "oops", T0),
    ],
)
def test_a_setting_that_cannot_be_read_stops_trading_instead_of_removing_the_limit(
    broken: AppSettingRecord,
) -> None:
    guard = make_guard()
    guard.load([broken], [])
    assert guard.kill_switch is True
    assert not guard.admit(request()).allowed


def test_todays_totals_are_rebuilt_from_stored_trades_after_a_restart() -> None:
    clock = ManualClock(datetime(2026, 11, 2, 12, 0, tzinfo=UTC))
    guard = make_guard(RiskLimits(daily_stop_loss=D("10.00")), clock)
    guard.load(
        [],
        [
            result("-9", at=datetime(2026, 11, 1, 23, 59, 59, tzinfo=UTC)),  # yesterday: ignored
            result("-6", at=datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC)),
            result("-5", at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)),
            result("-100", at=datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC), account=AccountType.REAL),
        ],
    )
    assert guard.day_pnl(AccountType.DEMO) == D("-11")
    assert guard.day_pnl(AccountType.DEMO, GROUP) == D("-11")
    assert not guard.admit(request()).allowed


def test_trade_ids_are_unique_so_reservations_do_not_collide() -> None:
    guard = make_guard(RiskLimits(max_concurrent_trades=100))
    ids = count()
    for _ in range(50):
        next(ids)
        assert guard.admit(request()).allowed
    assert guard.open_trades == 50


def test_a_day_is_one_day_after_the_clock_moves_a_full_day() -> None:
    clock = ManualClock()
    guard = make_guard(None, clock)
    first = guard.current_day_start
    clock.advance(timedelta(days=1).total_seconds())
    assert guard.current_day_start - first == timedelta(days=1)
