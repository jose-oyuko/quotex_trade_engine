from __future__ import annotations

import pytest

from app.telegram import FakeTelegramSource, TelegramLoginError
from app.telegram.login import log_in, normalise_phone
from tests.signal_support import ManualClock


class Answers:
    """Plays the part of the person at the terminal and remembers what they were asked."""

    def __init__(
        self, code: str = "12345", password: str = "", first: list[str] | None = None
    ) -> None:
        self.code, self.password = code, password
        self.first = list(first or [])  # answers given before the real code (for example "sms")
        self.asked: list[str] = []

    async def ask_code(self, prompt: str) -> str:
        self.asked.append(prompt)
        if self.first:
            return self.first.pop(0)
        return f"  {self.code}\n"

    async def ask_password(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.password


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("+254712345678", "+254712345678"),
        ("+254 712 345 678", "+254712345678"),
        (" +1 (415) 555-0100 ", "+14155550100"),
        ("+44-7911-123456", "+447911123456"),
    ],
)
def test_phone_numbers_are_cleaned_up(typed: str, expected: str) -> None:
    assert normalise_phone(typed) == expected


@pytest.mark.parametrize("typed", ["0712345678", "254712345678", "+0712345678", "+12", "", "abc"])
def test_phone_numbers_must_be_international(typed: str) -> None:
    with pytest.raises(TelegramLoginError, match="international"):
        normalise_phone(typed)


async def test_login_with_a_code() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False, login_code="55555")
    answers = Answers(code="55555")
    await log_in(
        source,
        phone="+254 712 345 678",
        ask_code=answers.ask_code,
        ask_password=answers.ask_password,
    )
    assert await source.is_authorized()
    assert len(answers.asked) == 1  # only the code, no password


async def test_login_with_two_step_verification_asks_for_the_password_too() -> None:
    source = FakeTelegramSource(
        ManualClock(), authorized=False, login_code="55555", two_step_password="s3cret"
    )
    answers = Answers(code="55555", password="s3cret")
    await log_in(
        source, phone="+254712345678", ask_code=answers.ask_code, ask_password=answers.ask_password
    )
    assert await source.is_authorized()
    assert len(answers.asked) == 2


async def test_an_already_logged_in_session_is_not_asked_anything() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=True)
    answers = Answers()
    await log_in(
        source,
        phone="not even checked",
        ask_code=answers.ask_code,
        ask_password=answers.ask_password,
    )
    assert answers.asked == []


async def test_a_wrong_code_is_reported_and_leaves_the_session_logged_out() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False, login_code="55555")
    answers = Answers(code="00000")
    with pytest.raises(TelegramLoginError, match="wrong code"):
        await log_in(
            source,
            phone="+254712345678",
            ask_code=answers.ask_code,
            ask_password=answers.ask_password,
        )
    assert not await source.is_authorized()


async def test_a_wrong_password_is_reported() -> None:
    source = FakeTelegramSource(
        ManualClock(), authorized=False, login_code="55555", two_step_password="s3cret"
    )
    answers = Answers(code="55555", password="guess")
    with pytest.raises(TelegramLoginError, match="wrong password"):
        await log_in(
            source,
            phone="+254712345678",
            ask_code=answers.ask_code,
            ask_password=answers.ask_password,
        )
    assert not await source.is_authorized()


async def test_a_bad_phone_number_is_refused_before_anything_is_sent() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False)
    answers = Answers()
    with pytest.raises(TelegramLoginError):
        await log_in(
            source, phone="0712345678", ask_code=answers.ask_code, ask_password=answers.ask_password
        )
    assert answers.asked == []


async def test_the_person_is_told_where_the_code_went() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False, login_code="55555")
    answers = Answers(code="55555")
    await log_in(
        source, phone="+254712345678", ask_code=answers.ask_code, ask_password=answers.ask_password
    )
    assert "to your Telegram app" in answers.asked[0]
    assert "sms" in answers.asked[0].lower()


async def test_typing_sms_asks_telegram_to_send_the_code_another_way() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False, login_code="55555")
    answers = Answers(code="55555", first=["sms"])
    await log_in(
        source, phone="+254712345678", ask_code=answers.ask_code, ask_password=answers.ask_password
    )
    assert await source.is_authorized()
    assert source.resends == 1
    assert "to your Telegram app" in answers.asked[0]
    assert "by SMS" in answers.asked[1]  # the second prompt says the new place


async def test_when_telegram_has_no_other_way_the_login_fails_with_a_reason() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False)
    answers = Answers(first=["sms", "sms"])  # the fake allows one resend
    with pytest.raises(TelegramLoginError, match="no other way"):
        await log_in(
            source,
            phone="+254712345678",
            ask_code=answers.ask_code,
            ask_password=answers.ask_password,
        )


async def test_asking_for_sms_over_and_over_is_bounded() -> None:
    source = FakeTelegramSource(ManualClock(), authorized=False)
    source.max_resends = 99
    answers = Answers(first=["sms"] * 10)
    with pytest.raises(TelegramLoginError, match="would not send the code again"):
        await log_in(
            source,
            phone="+254712345678",
            ask_code=answers.ask_code,
            ask_password=answers.ask_password,
        )
    assert source.resends == 2
