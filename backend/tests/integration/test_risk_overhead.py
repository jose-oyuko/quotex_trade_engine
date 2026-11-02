"""What the RiskGuard costs on the way to an order (docs/PHASES.md Phase 5).

Bounds are loose so the test cannot flake; the real figures (run with `-s`) are in the phase report.
"""

from __future__ import annotations

import statistics
import time
from decimal import Decimal

from app.domain.enums import AccountType, TradeStatus
from app.domain.ids import new_id
from app.engine.risk import GroupRiskLimits, OrderRequest, RiskGuard, RiskLimits
from app.events.bus import EventBus
from tests.engine_support import measure_latency
from tests.factories import make_trade
from tests.signal_support import ManualClock

D = Decimal
COUNT = 20_000


def fully_configured_guard() -> RiskGuard:
    """Every limit switched on, so every comparison in `admit` actually runs."""
    guard = RiskGuard(
        clock=ManualClock(),
        bus=EventBus(),
        limits=RiskLimits(
            max_stake=D("100"),
            max_concurrent_trades=1000,
            max_exposure=D("100000"),
            max_chain_trades=20,
            daily_stop_loss=D("1000"),
            daily_profit_target=D("1000"),
        ),
    )
    guard.set_group_limits(
        1,
        GroupRiskLimits(max_stake=D("50"), daily_stop_loss=D("500"), daily_profit_target=D("500")),
    )
    return guard


def test_admitting_and_settling_an_order_costs_microseconds() -> None:
    guard = fully_configured_guard()
    requests = [
        OrderRequest(new_id(), new_id(), 1, "EURUSD", 0, D("1.00"), AccountType.DEMO, 85, 80)
        for _ in range(COUNT)
    ]
    trades = [
        make_trade(
            r.chain_id,
            1,
            id=r.trade_id,
            status=TradeStatus.WON if n % 2 == 0 else TradeStatus.LOST,
            profit=D("0.85") if n % 2 == 0 else D("-0.85"),
        )
        for n, r in enumerate(requests)
    ]  # alternating results keep the day's total near zero, below every limit
    admit_ns: list[int] = []
    settle_ns: list[int] = []
    for request, trade in zip(requests, trades, strict=True):
        t0 = time.perf_counter_ns()
        decision = guard.admit(request)
        t1 = time.perf_counter_ns()
        guard.settled(trade)
        t2 = time.perf_counter_ns()
        assert decision.allowed
        admit_ns.append(t1 - t0)
        settle_ns.append(t2 - t1)

    def line(name: str, samples: list[int]) -> float:
        ordered = sorted(samples)
        median, p99 = statistics.median(ordered) / 1000, ordered[int(len(ordered) * 0.99)] / 1000
        print(
            f"\n{name}: median {median:.1f} us, p99 {p99:.1f} us, worst {ordered[-1] / 1000:.0f} us"
        )
        return median

    admit_median = line(f"RiskGuard.admit   ({COUNT} orders, all limits on)", admit_ns)
    line(f"RiskGuard.settled ({COUNT} orders)", settle_ns)
    assert admit_median < 100  # microseconds; typically a few
    assert guard.open_trades == 0


async def test_the_whole_path_stays_in_microseconds_with_the_guard_in_it() -> None:
    samples = await measure_latency(300, through_parser=False)
    ordered = sorted(samples)
    median_us = statistics.median(ordered) / 1000
    p99_us = ordered[int(len(ordered) * 0.99)] / 1000
    print(f"\nsignal -> place_order with the guard: median {median_us:.0f} us, p99 {p99_us:.0f} us")
    assert median_us < 2_000
    assert p99_us < 10_000
