"""Back up (and restore) the application's data.

    npm run backup                         make a backup in backups/quotex-<date>-<time>/
    npm run backup -- --no-secrets         leave the login/session files out
    npm run backup -- --keep 30            keep the newest 30 backups (default 14)
    npm run backup -- --restore backups/quotex-20261102-093000 --yes

What is saved: the database (`quotex.db`: every trade, chain, signal, setting), taken with SQLite's
own online-backup call so it is a consistent copy even while the app is running, plus the saved
logins (`telegram.session`, `session.json`) unless `--no-secrets`. Not saved: `backend/.env` (your
passwords; keep your own copy somewhere safe) and the log files.

**A backup with the session files in it is as sensitive as your passwords.** Keep it somewhere only
you can read.

Restoring replaces the database with the backup's. The current database is kept next to it as
`quotex.db.before-restore-<time>`, so a mistake can be undone. Stop the app first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DEFAULT_DIR = ROOT / "backups"
DATABASE = "quotex.db"
SECRET_FILES = ("telegram.session", "session.json")
PREFIX = "quotex-"
DEFAULT_KEEP = 14
COUNTED_TABLES = ("groups", "signals", "chains", "trades", "risk_events", "balance_snapshots")


class BackupError(Exception):
    """Something the owner has to know: the message says what and what to do."""


@dataclass(slots=True, frozen=True)
class BackupResult:
    folder: Path
    files: list[str]
    integrity: str
    rows: dict[str, int]


def _check(db: sqlite3.Connection) -> str:
    row = db.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no answer"


def _count_rows(db: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in COUNTED_TABLES:
        try:
            counts[table] = int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
        except sqlite3.OperationalError:
            counts[table] = 0  # a table that does not exist yet
    return counts


def make_backup(
    data_dir: Path,
    into: Path,
    *,
    include_secrets: bool = True,
    keep: int = DEFAULT_KEEP,
    now: datetime | None = None,
) -> BackupResult:
    """Copy the database (consistently) and the session files to a new folder under `into`."""
    source = data_dir / DATABASE
    if not source.is_file():
        raise BackupError(f"There is no database at {source}: nothing to back up yet.")
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    folder = into / f"{PREFIX}{stamp}"
    if folder.exists():
        raise BackupError(f"{folder} already exists (a backup in the same second?). Try again.")
    folder.mkdir(parents=True)

    live = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    copy = sqlite3.connect(folder / DATABASE)
    try:
        live.backup(copy)  # SQLite's online backup: consistent even while the app writes
        integrity = _check(copy)
        rows = _count_rows(copy)
    except sqlite3.DatabaseError as exc:  # the file is damaged: SQLite cannot even read it
        integrity = f"unreadable: {exc}"
        rows = {}
    finally:
        copy.close()
        live.close()
    if integrity != "ok":
        shutil.rmtree(folder)
        raise BackupError(f"The database failed its integrity check ({integrity}); no backup made.")

    files = [DATABASE]
    if include_secrets:
        for name in SECRET_FILES:
            if (data_dir / name).is_file():
                shutil.copy2(data_dir / name, folder / name)
                files.append(name)
    manifest = {
        "made_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "files": files,
        "integrity": integrity,
        "rows": rows,
        "includes_secrets": include_secrets,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    prune(into, keep)
    return BackupResult(folder, files, integrity, rows)


def prune(into: Path, keep: int) -> list[Path]:
    """Delete the oldest backups beyond the newest `keep`. Only folders this script made."""
    if keep < 1:
        raise BackupError("--keep must be at least 1")
    folders = sorted(
        p
        for p in into.iterdir()
        if p.is_dir() and p.name.startswith(PREFIX) and (p / "manifest.json").is_file()
    )
    doomed = folders[:-keep] if len(folders) > keep else []
    for folder in doomed:
        shutil.rmtree(folder)
    return doomed


def restore(backup: Path, data_dir: Path, *, now: datetime | None = None) -> Path:
    """Put a backup's database (and sessions) in place; returns where the old database went."""
    source = backup / DATABASE
    if not (backup / "manifest.json").is_file() or not source.is_file():
        raise BackupError(
            f"{backup} is not a backup made by this tool (no manifest.json / {DATABASE})."
        )
    check = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        integrity = _check(check)
    except sqlite3.DatabaseError as exc:
        integrity = f"unreadable: {exc}"
    finally:
        check.close()
    if integrity != "ok":
        raise BackupError(f"The backup is damaged ({integrity}); nothing was changed.")

    data_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    current = data_dir / DATABASE
    kept = data_dir / f"{DATABASE}.before-restore-{stamp}"
    if current.exists():
        current.replace(kept)
    for leftover in (data_dir / f"{DATABASE}-wal", data_dir / f"{DATABASE}-shm"):
        leftover.unlink(missing_ok=True)  # they belong to the database that was just put aside
    shutil.copy2(source, current)
    for name in SECRET_FILES:
        if (backup / name).is_file():
            shutil.copy2(backup / name, data_dir / name)
    return kept


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-secrets", action="store_true", help="leave session files out")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="how many backups to keep")
    parser.add_argument("--to", type=Path, default=DEFAULT_DIR, help="folder for backups")
    parser.add_argument("--restore", type=Path, help="restore from this backup folder")
    parser.add_argument("--yes", action="store_true", help="confirm a restore")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.stderr.write(f"Invalid configuration:\n{exc}\n")
        return 2
    data_dir = settings.data_dir.resolve()
    try:
        if args.restore is not None:
            if not args.yes:
                sys.stderr.write(
                    "Restoring replaces the current database with the backup's (the current one "
                    "is kept beside it). Stop the app, then add --yes to go ahead.\n"
                )
                return 1
            kept = restore(args.restore, data_dir)
            print(f"Restored {args.restore}. The previous database is kept as {kept}.")
            return 0
        args.to.mkdir(parents=True, exist_ok=True)
        result = make_backup(data_dir, args.to, include_secrets=not args.no_secrets, keep=args.keep)
    except BackupError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    print(f"Backup saved in {result.folder}")
    print(f"  files: {', '.join(result.files)}   integrity: {result.integrity}")
    print("  rows:  " + ", ".join(f"{k} {v}" for k, v in result.rows.items()))
    if any(name in result.files for name in SECRET_FILES):
        print("  NOTE: this backup contains your saved logins. Keep it private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
