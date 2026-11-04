"""Password hashing and the login throttle, with the real (full-cost) settings."""

from __future__ import annotations

import time

import pytest

from app.auth import passwords
from app.auth.passwords import hash_password, password_problem, verify_password
from app.auth.throttle import LoginThrottle


def test_a_password_verifies_against_its_own_hash_only() -> None:
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batter", stored)
    assert not verify_password("", stored)


def test_the_hash_does_not_contain_the_password_and_differs_every_time() -> None:
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert "correct horse" not in first
    assert first != second  # a fresh random salt each time
    assert first.startswith(f"scrypt${passwords.N}${passwords.R}${passwords.P}$")


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "plain-text",
        "scrypt$1$2$3$4",
        "bcrypt$1$2$3$4$5",
        "scrypt$x$8$3$AAAA$AAAA",
        "scrypt$$$$$",
    ],
)
def test_a_malformed_hash_never_matches_and_never_raises(stored: str) -> None:
    assert verify_password("anything at all", stored) is False


def test_an_old_hash_still_verifies_after_the_cost_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cost is stored in the hash, so raising the constants later does not lock anyone out."""
    monkeypatch.setattr(passwords, "N", 2**4)
    stored = hash_password("correct horse battery")
    monkeypatch.setattr(passwords, "N", 2**14)
    assert verify_password("correct horse battery", stored)


def test_hashing_is_slow_enough_to_matter_and_not_slower_than_a_second() -> None:
    started = time.perf_counter()
    hash_password("correct horse battery")
    elapsed = time.perf_counter() - started
    assert 0.005 < elapsed < 2.0, elapsed  # a guard against an accidental cost of 1 or of 2**25


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("short", "at least 10"),
        ("x" * 257, "at most 256"),
        ("OwnerName", "10"),  # too short wins over the same-as-username rule
        ("          ", "only spaces"),
    ],
)
def test_unacceptable_passwords_say_why(password: str, fragment: str) -> None:
    problem = password_problem(password, "OwnerName")
    assert problem is not None and fragment in problem


def test_a_password_equal_to_the_username_is_refused() -> None:
    problem = password_problem("the-owner-name", "The-Owner-Name")
    assert problem is not None and "same as the username" in problem


def test_a_good_password_has_no_problem() -> None:
    assert password_problem("correct horse battery", "owner") is None


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_five_failures_lock_a_name_until_the_lock_runs_out() -> None:
    clock = Clock()
    throttle = LoginThrottle(max_failures=5, lock_seconds=900, now=clock)
    for _ in range(4):
        throttle.failed("user:owner")
    assert throttle.seconds_locked("user:owner") == 0  # four failures: still allowed
    throttle.failed("user:owner")
    assert 0 < throttle.seconds_locked("user:owner") <= 901
    clock.t += 899
    assert throttle.seconds_locked("user:owner") > 0
    clock.t += 2
    assert throttle.seconds_locked("user:owner") == 0
    throttle.failed("user:owner")  # the count started again from zero
    assert throttle.seconds_locked("user:owner") == 0


def test_a_success_clears_the_failures_and_names_are_independent() -> None:
    throttle = LoginThrottle(max_failures=3, lock_seconds=900, now=Clock())
    for _ in range(2):
        throttle.failed("user:a")
    throttle.succeeded("user:a")
    throttle.failed("user:a")
    assert throttle.seconds_locked("user:a") == 0
    for _ in range(3):
        throttle.failed("user:b")
    assert throttle.seconds_locked("user:b") > 0
    assert throttle.seconds_locked("user:a") == 0


def test_the_throttle_does_not_grow_without_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.auth.throttle.MAX_TRACKED", 50)
    throttle = LoginThrottle(now=Clock())
    for i in range(500):
        throttle.failed(f"user:{i}")
    assert len(throttle._failures) <= 50
