"""Create the owner account, or set a new password, from the machine the application runs on.

    npm run owner:reset

Use it when you forgot the password (there is no email to send a reset link to), or to create the
account without the setup code. It changes the database directly and ends every logged-in browser.
It works whether or not the application is running. The password is typed without echo and is
never printed or stored anywhere but as a hash.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable

from sqlalchemy import func, select

from app.auth.service import AuthError, AuthService
from app.core.clock import SystemClock
from app.core.config import Settings, get_settings
from app.db.engine import create_engine, create_session_factory
from app.db.migrations import schema_is_current
from app.db.models import User

Ask = Callable[[str], str]


async def reset_owner(settings: Settings, *, ask: Ask, ask_secret: Ask) -> str:
    """Do the work; returns a sentence for the owner. Raises `AuthError` for a refused input and
    `RuntimeError` if the database is not set up."""
    engine = create_engine(settings.database_url)
    try:
        if not settings.database_path.exists() or not await schema_is_current(engine):
            raise RuntimeError("The database is missing or out of date. Run `npm run db:upgrade`.")
        factory = create_session_factory(engine)
        async with factory() as session:
            exists = bool(await session.scalar(select(func.count()).select_from(User)))
        username = None if exists else ask("Choose a username for the owner account: ").strip()
        password = ask_secret("New password: ")
        if password != ask_secret("Type it again: "):
            raise AuthError("The two passwords are not the same. Nothing was changed.")
        name, created = await AuthService(factory, SystemClock()).set_owner(
            username=username, password=password
        )
    finally:
        await engine.dispose()
    if created:
        return f"Created the owner account {name!r}. Log in with it on the dashboard."
    return f"New password set for {name!r}. Every logged-in browser was logged out."


def main(argv: list[str]) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    try:
        message = asyncio.run(
            reset_owner(
                get_settings(), ask=input, ask_secret=lambda prompt: getpass.getpass(prompt)
            )
        )
    except (AuthError, RuntimeError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("\nCancelled. Nothing was changed.\n")
        return 1
    sys.stdout.write(f"{message}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
