"""Bus events -> WebSocket messages.

An event that produces no message (a stored setting that is not a control) does not get a sequence
number, so the numbers a client sees are always consecutive.
"""

from __future__ import annotations

from datetime import datetime

from app.api.schemas.records import (
    balance_out,
    chain_out,
    risk_event_out,
    signal_out,
    trade_out,
)
from app.api.schemas.ws import (
    AccountChangedMessage,
    AccountEventOut,
    BalanceUpdatedMessage,
    ChainAdvancedMessage,
    ChainEndedMessage,
    ChainStartedMessage,
    ConnectionChangedMessage,
    ConnectionEventOut,
    ControlsChangedMessage,
    RiskTrippedMessage,
    SignalReceivedMessage,
    TradeOpenedMessage,
    TradeSettledMessage,
)
from app.api.snapshot import SnapshotBuilder
from app.events.types import (
    AccountChanged,
    BalanceUpdated,
    ChainAdvanced,
    ChainEnded,
    ChainStarted,
    ConnectionChanged,
    Event,
    RiskTripped,
    SettingChanged,
    SignalReceived,
    TradeOpened,
    TradeSettled,
)
from app.services.live import is_control_setting

type EventMessage = (
    AccountChangedMessage
    | BalanceUpdatedMessage
    | ChainAdvancedMessage
    | ChainEndedMessage
    | ChainStartedMessage
    | ConnectionChangedMessage
    | ControlsChangedMessage
    | RiskTrippedMessage
    | SignalReceivedMessage
    | TradeOpenedMessage
    | TradeSettledMessage
)


def to_message(event: Event, seq: int, snapshots: SnapshotBuilder) -> EventMessage | None:
    """The message for `event`, numbered `seq`, or None if clients do not need to hear of it.
    Called after the live state has applied the event."""
    at: datetime = event.occurred_at
    match event:
        case SignalReceived(signal=signal):
            return SignalReceivedMessage(seq=seq, at=at, data=signal_out(signal))
        case ChainStarted(chain=chain):
            return ChainStartedMessage(seq=seq, at=at, data=chain_out(chain))
        case ChainAdvanced(chain=chain):
            return ChainAdvancedMessage(seq=seq, at=at, data=chain_out(chain))
        case ChainEnded(chain=chain):
            return ChainEndedMessage(seq=seq, at=at, data=chain_out(chain))
        case TradeOpened(trade=trade):
            return TradeOpenedMessage(seq=seq, at=at, data=trade_out(trade))
        case TradeSettled(trade=trade):
            return TradeSettledMessage(seq=seq, at=at, data=trade_out(trade))
        case RiskTripped(risk_event=risk_event):
            return RiskTrippedMessage(seq=seq, at=at, data=risk_event_out(risk_event))
        case BalanceUpdated(snapshot=snapshot):
            return BalanceUpdatedMessage(seq=seq, at=at, data=balance_out(snapshot))
        case ConnectionChanged(component=component, connected=connected, detail=detail):
            return ConnectionChangedMessage(
                seq=seq,
                at=at,
                data=ConnectionEventOut(component=component, connected=connected, detail=detail),
            )
        case AccountChanged(account_type=account_type):
            return AccountChangedMessage(
                seq=seq, at=at, data=AccountEventOut(account_type=account_type)
            )
        case SettingChanged(setting=setting) if is_control_setting(setting.key):
            return ControlsChangedMessage(seq=seq, at=at, data=snapshots.controls())
        case _:
            return None
