"""What the Settings page asks for before the engine can start: one broker's logins (D-75)."""

from __future__ import annotations

from app.engine.logins import BrokerChoice, LoginItem, broker_choices


def items(*present: str) -> list[LoginItem]:
    labels = (
        "Quotex email",
        "Quotex password",
        "Telegram API id",
        "Deriv app id",
        "Deriv demo token",
        "Deriv real token",
    )
    return [
        LoginItem(label, label in present, "dashboard" if label in present else "missing")
        for label in labels
    ]


def test_nothing_stored_offers_either_broker_in_full() -> None:
    assert broker_choices(items()) == [
        BrokerChoice("Deriv", ("Deriv app id", "Deriv demo token")),
        BrokerChoice("Quotex", ("Quotex email", "Quotex password")),
    ]


def test_a_deriv_token_without_the_app_id_asks_only_for_the_app_id_first() -> None:
    assert broker_choices(items("Deriv demo token")) == [
        BrokerChoice("Deriv", ("Deriv app id",)),
        BrokerChoice("Quotex", ("Quotex email", "Quotex password")),
    ]


def test_the_closest_broker_comes_first() -> None:
    choices = broker_choices(items("Quotex email", "Deriv real token"))
    assert choices[0] == BrokerChoice("Quotex", ("Quotex password",))


def test_one_ready_broker_is_enough_and_telegram_is_never_asked_for() -> None:
    assert broker_choices(items("Deriv app id", "Deriv demo token")) == []
    assert broker_choices(items("Quotex email", "Quotex password")) == []
