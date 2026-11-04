"""`npm run owner:reset`: creating the account and resetting the password from the machine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.auth import passwords
from app.auth.service import AuthError
from scripts.owner import reset_owner
from tests.api_support import migrate, running_api, settings_for


def answers(*values: str) -> object:
    queue = list(values)
    return lambda prompt: queue.pop(0)


@pytest.fixture(autouse=True)
def cheap_hashing() -> object:
    with patch.object(passwords, "N", 2**4):
        yield


async def test_it_creates_the_account_when_there_is_none_and_then_resets_the_password(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path)
    await migrate(settings)
    created = await reset_owner(
        settings,
        ask=answers("joseph"),  # type: ignore[arg-type]
        ask_secret=answers("a long enough password", "a long enough password"),  # type: ignore[arg-type]
    )
    assert "Created the owner account 'joseph'" in created

    # the second time it is a reset: it does not ask for a name, and it keeps the account's
    reset = await reset_owner(
        settings,
        ask=answers(),  # type: ignore[arg-type]
        ask_secret=answers("another long password", "another long password"),  # type: ignore[arg-type]
    )
    assert "New password set for 'joseph'" in reset


async def test_the_new_password_works_and_the_old_one_and_old_sessions_do_not(
    tmp_path: Path,
) -> None:
    async with running_api(tmp_path) as rig:
        assert (await rig.client.get("/api/v1/status")).status_code == 200
        await reset_owner(
            rig.settings,
            ask=answers(),  # type: ignore[arg-type]
            ask_secret=answers("brand new password", "brand new password"),  # type: ignore[arg-type]
        )
        assert (await rig.client.get("/api/v1/status")).status_code == 401  # logged out
        login = await rig.client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": "brand new password"}
        )
        assert login.status_code == 200


async def test_it_refuses_passwords_that_differ_or_are_weak_and_changes_nothing(
    tmp_path: Path,
) -> None:
    settings = settings_for(tmp_path)
    await migrate(settings)
    with pytest.raises(AuthError, match="not the same"):
        await reset_owner(
            settings,
            ask=answers("joseph"),  # type: ignore[arg-type]
            ask_secret=answers("a long enough password", "a different one entirely"),  # type: ignore[arg-type]
        )
    with pytest.raises(AuthError, match="at least 10"):
        await reset_owner(
            settings,
            ask=answers("joseph"),  # type: ignore[arg-type]
            ask_secret=answers("short", "short"),  # type: ignore[arg-type]
        )
    with pytest.raises(AuthError, match="username"):
        await reset_owner(
            settings,
            ask=answers("x"),  # type: ignore[arg-type]
            ask_secret=answers("a long enough password", "a long enough password"),  # type: ignore[arg-type]
        )


async def test_it_says_so_when_the_database_is_not_set_up(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)  # no migration
    with pytest.raises(RuntimeError, match="db:upgrade"):
        await reset_owner(
            settings,
            ask=answers(),  # type: ignore[arg-type]
            ask_secret=answers(),  # type: ignore[arg-type]
        )
