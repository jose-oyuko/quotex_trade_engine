"""An early result that Deriv's own result contradicts (decision D-82): the trade is corrected, the
day's figures with it, and the risk log says so."""

from __future__ import annotations

from decimal import Decimal

from app.brokers.base import TradeOutcome
from app.domain.enums import AccountType, Broker, Strategy, TradeStatus
from app.events.types import RiskTripped
from tests.engine_support import GroupSpec, make_rig

D = Decimal
DV_GROUP, DV_CHAT = 2, -1002


async def test_a_corrected_result_replaces_the_early_one_loudly() -> None:
    rig = make_rig(with_deriv=True, hold_results=True)
    rig.add_group(GroupSpec(DV_GROUP, DV_CHAT, Strategy.NO_MARTINGALE, broker=Broker.DERIV))
    await rig.start()
    fake = rig.deriv
    assert fake is not None
    fake.script_results(TradeOutcome.WON)  # reported (early) as a win at 81 %
    rig.signal(DV_CHAT, "GBPUSD PUT 15m")
    await rig.until(lambda: len(fake.orders) == 1)
    fake.settle_all()
    await rig.idle()
    guard = rig.engine.guard
    assert guard.day_pnl(AccountType.DEMO, broker=Broker.DERIV) == D("0.81")

    fake.correct(fake.orders[0].order_id, D("-1.00"))  # Deriv's own result: a loss

    [trade] = rig.trades("GBPUSD")
    assert (trade.status, trade.profit) == (TradeStatus.LOST, D("-1.00"))
    assert trade.error is not None and "reported early as won 0.81" in trade.error
    assert guard.day_pnl(AccountType.DEMO, broker=Broker.DERIV) == D("-1.00")
    [event] = [e for e in rig.collect() if isinstance(e, RiskTripped)]
    assert event.risk_event.kind == "early_result_corrected"
    await rig.stop()


async def test_a_correction_for_a_trade_no_longer_remembered_changes_nothing() -> None:
    rig = make_rig(with_deriv=True)
    await rig.start()
    assert rig.deriv is not None
    rig.deriv.correct("123456", D("-1.00"))
    assert not [e for e in rig.collect() if isinstance(e, RiskTripped)]
    await rig.stop()
