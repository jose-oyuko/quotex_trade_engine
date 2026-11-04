"""Move the logins written in `backend/.env` into the encrypted store, and tidy the file.

    npm run env:import                 show what would move, ask, move it, tidy `.env`
    npm run env:import -- --yes        the same without asking

Before the dashboard could take logins, they were typed into `backend/.env` in plain text. They
still work, but a login stored on the dashboard wins over them, and they are better not left in
plain text. This copies each one that the store does not have yet into the store (encrypted with
`SECRET_KEY`), then replaces its line in `.env` by a comment (the value is removed from the file).
It never overwrites a stored login. It also retires two lines the application no longer reads:
ENGINE_ENABLED (if it was `true` and the dashboard never decided, the engine is left running, so
it starts with the application as before) and QUOTEX_ALLOW_REAL (never carried over: real money
is allowed on the dashboard, with your password). Values are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.services.env_import import EnvImportService
from app.vault.errors import VaultError
from scripts._store import StoreUnavailableError, open_store

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_LINE = re.compile(r"^(\s*)([A-Z][A-Z0-9_]*)(\s*=.*?)(\r?\n?)$", re.DOTALL)
RETIRED = ("ENGINE_ENABLED", "QUOTEX_ALLOW_REAL")
TRUE_WORDS = {"true", "1", "yes"}


def env_value(text: str, name: str) -> str | None:
    """The value of the last active `NAME=` line in `text` (quotes removed), or None."""
    value: str | None = None
    for line in text.splitlines():
        match = _LINE.match(line)
        if match and match.group(2) == name:
            value = match.group(3).split("=", 1)[1].strip().strip("\"'")
    return value


def read_env(env_file: Path) -> str:
    # bytes, not text: reading as text would turn Windows line endings into plain ones
    return env_file.read_bytes().decode("utf-8") if env_file.is_file() else ""


def write_env(env_file: Path, text: str) -> None:
    env_file.write_bytes(text.encode("utf-8"))


def tidy(text: str, moved: set[str]) -> str:
    """`text` with the lines of the moved logins (given by their store names, such as
    `quotex_email`) and of the retired switches turned into comments that hold no value.
    Everything else, line endings included, is left exactly as it was."""
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _LINE.match(line)
        name = match.group(2) if match else None
        eol = match.group(4) if match else ""
        if match and name is not None and name.lower() in moved:  # `moved` holds secret names
            out.append(f"# {name}=   (moved to the encrypted store){eol}")
        elif match and name in RETIRED:
            out.append(f"# {name} is no longer read: it is set on the dashboard now{eol}")
        else:
            out.append(line)
    return "".join(out)


async def run_import(
    settings: Settings,
    env_file: Path,
    *,
    yes: bool,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> int:
    try:
        store = await open_store(settings)
    except StoreUnavailableError as exc:
        say(str(exc))
        return 1
    try:
        text = await asyncio.to_thread(read_env, env_file)
        service = EnvImportService(store.vault, lambda: settings)
        before = await service.status()
        # the logins whose lines go: already stored, or about to be
        to_clear = {item.name for item in before if item.in_env}
        engine_was_on = (env_value(text, "ENGINE_ENABLED") or "").lower() in TRUE_WORDS
        real_was_on = (env_value(text, "QUOTEX_ALLOW_REAL") or "").lower() in TRUE_WORDS
        retired_present = any(env_value(text, name) is not None for name in RETIRED)
        if not to_clear and not retired_present:
            say("Nothing to move: backend/.env holds none of the old logins or switches.")
            return 0
        for item in before:
            if item.in_env:
                say(f"  {item.label}: " + ("already stored" if item.stored else "will be moved"))
        if retired_present:
            say("  ENGINE_ENABLED / QUOTEX_ALLOW_REAL: no longer read; their lines will be retired")
        if not yes and ask("Move them and tidy backend/.env? [y/N] ").strip().lower() not in {
            "y",
            "yes",
        }:
            say("Nothing was changed.")
            return 1
        try:
            moved = await service.import_all()
        except VaultError as exc:
            say(f"Nothing was changed: {exc}")
            return 1
        if engine_was_on and await store.flags.desired() is None:
            await store.flags.set_desired(True)
            say("The engine is left running: it starts with the application, as it did before.")
        if real_was_on:
            say(
                "QUOTEX_ALLOW_REAL=true was NOT carried over: allow real money on the dashboard's "
                "Settings page, with your password."
            )
        tidied = tidy(text, to_clear)
        if tidied != text:
            await asyncio.to_thread(write_env, env_file, tidied)
        say(f"Moved {len(moved)} login(s) into the encrypted store; backend/.env was tidied.")
        say("Restart the application (and the engine) so it uses them.")
        return 0
    finally:
        await store.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="do not ask")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"Invalid configuration in backend/.env:\n{exc}\n")
        return 2
    try:
        return asyncio.run(run_import(settings, ENV_FILE, yes=args.yes))
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("\nCancelled. Nothing was changed.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
