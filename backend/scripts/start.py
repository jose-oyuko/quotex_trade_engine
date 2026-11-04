"""One command to run everything: `npm start` (or double-click `start.bat` on Windows).

    npm start                       prepare, then run the app and open the dashboard
    npm start -- --no-browser       the same, without opening a browser window
    npm start -- --prepare-only     do the preparation and stop (to check a new installation)

Preparation, each step skipped when it is already done:
  1. check that Node.js is installed (the dashboard is built with it)
  2. install the dashboard's packages if they are missing
  3. build the dashboard if it is missing or older than its source
  4. create or update the database (`alembic upgrade head`)
  5. make sure `SECRET_KEY` exists in backend/.env (it encrypts the logins stored in the dashboard)
  6. check that the port is free, and show how the app is configured (never the secrets)
Then the backend serves both the API and the dashboard on one address.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from pydantic import ValidationError

from app.core.config import Settings
from app.db.migrations import alembic_config
from app.vault.key import ensure_secret_key

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
FRONTEND = ROOT / "frontend"
SOURCE_SUFFIXES = (".ts", ".tsx", ".css", ".html", ".json", ".svg")

type Runner = Callable[[Sequence[str], Path], int]
type Say = Callable[[str], None]


class StartError(Exception):
    """Something the owner has to fix before the app can start; the message says what to do."""


def run_command(command_line: Sequence[str], cwd: Path) -> int:
    return subprocess.run(command_line, cwd=cwd, check=False).returncode  # noqa: S603


def newest_source_time(src: Path, extras: Sequence[Path]) -> float:
    """Modification time of the newest file the dashboard is built from."""
    times = [
        p.stat().st_mtime for p in src.rglob("*") if p.is_file() and p.suffix in SOURCE_SUFFIXES
    ]
    times += [p.stat().st_mtime for p in extras if p.is_file()]
    return max(times, default=0.0)


def dashboard_needs_build(frontend: Path) -> bool:
    built = frontend / "dist" / "index.html"
    if not built.is_file():
        return True
    extras = [frontend / "package.json", frontend / "index.html", frontend / "vite.config.ts"]
    return newest_source_time(frontend / "src", extras) > built.stat().st_mtime


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


@dataclass(slots=True, frozen=True)
class Summary:
    """What the owner is about to run, with no secret in it."""

    url: str
    environment: str
    engine: str
    account: str
    credentials: list[str]
    data_dir: str
    log_file: str | None

    def lines(self) -> list[str]:
        out = [
            f"Address:      {self.url}",
            f"Environment:  {self.environment}",
            f"Trading:      {self.engine}",
            f"Account:      {self.account}",
            f"Data folder:  {self.data_dir}",
        ]
        if self.log_file:
            out.append(f"Log file:     {self.log_file}")
        out.extend(self.credentials)
        return out


def summarise(settings: Settings, *, env_file_exists: bool) -> Summary:
    credentials: list[str] = []
    if not env_file_exists:
        credentials.append("Settings:     no backend/.env: defaults are used (safe, trading off)")
    # The engine is started and stopped on the dashboard (decision D-63) and the application
    # remembers what the owner left running, so all the summary can do is say where.
    engine_text = (
        "start and stop it on the dashboard's Settings page (it starts on the demo account)"
    )
    return Summary(
        url=f"http://{settings.host}:{settings.port}",
        environment=settings.environment,
        engine=engine_text,
        account="demo (real money is allowed only on the dashboard, with your password)",
        credentials=credentials,
        data_dir=str(settings.data_dir.resolve()),
        log_file=str(settings.log_path) if settings.log_to_file else None,
    )


def prepare(
    settings: Settings,
    *,
    run: Runner = run_command,
    which: Callable[[str], str | None] = shutil.which,
    env_file: Path,
    frontend: Path = FRONTEND,
    say: Say = print,
    migrate: Callable[[Settings], None] | None = None,
    port_busy: Callable[[str, int], bool] = port_in_use,
) -> Summary:
    """Everything that must be true before the server starts. Raises `StartError` with advice."""
    npm = which("npm")
    if npm is None:
        raise StartError(
            "Node.js is not installed (the `npm` command was not found). Install Node.js 22 or "
            "newer from https://nodejs.org, then run this again."
        )
    if not (frontend / "node_modules").is_dir():
        say("Installing the dashboard's packages (first run only, needs the internet)...")
        if run([npm, "install"], frontend) != 0:
            raise StartError("`npm install` failed. Check your internet connection and try again.")
    if dashboard_needs_build(frontend):
        say("Building the dashboard...")
        if run([npm, "run", "build"], frontend) != 0:
            raise StartError("Building the dashboard failed. The messages above say why.")
    say("Preparing the database...")
    (migrate or _migrate)(settings)
    if ensure_secret_key(env_file):
        say(
            "Created SECRET_KEY in backend/.env: it encrypts the logins you store in the "
            "dashboard. Keep a copy of that file somewhere safe; without the key they cannot "
            "be read again."
        )
    if port_busy(settings.host, settings.port):
        raise StartError(
            f"Port {settings.port} is already in use. Is the app already running? Open "
            f"http://{settings.host}:{settings.port}, or stop the other program, or choose "
            "another port with PORT=... in backend/.env."
        )
    return summarise(settings, env_file_exists=(BACKEND / ".env").is_file())


def _migrate(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings.database_url), "head")


def open_when_ready(
    url: str, *, attempts: int = 120, opener: Callable[[str], object] = webbrowser.open
) -> None:
    """Open the browser as soon as the app answers (in a background thread; never blocks)."""

    def wait() -> None:
        for _ in range(attempts):
            try:
                with urllib.request.urlopen(f"{url}/api/v1/health", timeout=1):  # noqa: S310
                    opener(url)
                    return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=wait, daemon=True).start()


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"Invalid configuration in backend/.env:\n{exc}\n")
        return 2
    try:
        summary = prepare(settings, env_file=BACKEND / ".env")
    except StartError as exc:
        sys.stderr.write(f"\nCannot start: {exc}\n")
        return 1
    print("\n" + "\n".join(summary.lines()) + "\n")
    if args.prepare_only:
        print("Everything is ready. Run `npm start` to start the app.")
        return 0
    if not args.no_browser:
        open_when_ready(summary.url)
    print("Starting. Press Ctrl+C to stop.\n")
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
