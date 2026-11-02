"""`npm run backup`: a consistent copy of the data, easy to restore, never leaving secrets behind
unless asked to."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.backup import (
    DATABASE,
    PREFIX,
    BackupError,
    make_backup,
    prune,
    restore,
)

T0 = datetime(2026, 11, 2, 9, 30, 0, tzinfo=UTC)


def make_data(folder: Path, *, rows: int = 3, wal: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / DATABASE)
    if wal:
        db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, note TEXT)")
    db.executemany("INSERT INTO trades (note) VALUES (?)", [(f"trade {n}",) for n in range(rows)])
    db.commit()
    db.close()
    (folder / "telegram.session").write_text("SECRET-TELEGRAM-LOGIN", encoding="utf-8")
    (folder / "session.json").write_text('{"token": "SECRET-QUOTEX"}', encoding="utf-8")
    return folder


def notes(path: Path) -> list[str]:
    db = sqlite3.connect(path)
    try:
        return [r[0] for r in db.execute("SELECT note FROM trades ORDER BY id")]
    finally:
        db.close()


def scribble(path: Path) -> None:
    """Damage a database file the way a failing disk might."""
    raw = bytearray(path.read_bytes())
    for offset in range(4096 * 2, len(raw) - 100, 997):
        raw[offset] = 0xFF
    path.write_bytes(bytes(raw))


def test_a_backup_is_a_consistent_openable_copy_with_a_manifest(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", rows=5)
    result = make_backup(data, tmp_path / "backups", now=T0)
    assert result.folder.name == "quotex-20261102-093000"
    assert notes(result.folder / DATABASE) == [f"trade {n}" for n in range(5)]
    assert result.integrity == "ok"
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"] == [DATABASE, "telegram.session", "session.json"]
    assert manifest["includes_secrets"] is True and manifest["integrity"] == "ok"
    assert manifest["made_at"] == "2026-11-02T09:30:00+00:00"


def test_it_copes_with_a_database_in_wal_mode_that_is_open_and_busy(tmp_path: Path) -> None:
    """The real database runs in WAL mode with the application connected: the copy must still be
    whole, including what is only in the write-ahead log."""
    data = make_data(tmp_path / "data", rows=2, wal=True)
    live = sqlite3.connect(data / DATABASE)  # the "running application"
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("INSERT INTO trades (note) VALUES ('only in the log')")
    live.commit()  # committed, but not yet merged into the main file
    try:
        result = make_backup(data, tmp_path / "backups", now=T0)
    finally:
        live.close()
    assert "only in the log" in notes(result.folder / DATABASE)


def test_secrets_can_be_left_out(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data")
    result = make_backup(data, tmp_path / "backups", include_secrets=False, now=T0)
    assert sorted(p.name for p in result.folder.iterdir()) == ["manifest.json", DATABASE]
    for path in result.folder.rglob("*"):
        if path.is_file() and path.suffix != ".db":
            assert "SECRET" not in path.read_text(encoding="utf-8")


def test_the_original_is_never_touched(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data")
    before = (data / DATABASE).read_bytes()
    make_backup(data, tmp_path / "backups", now=T0)
    assert (data / DATABASE).read_bytes() == before


def test_without_a_database_there_is_nothing_to_back_up(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    with pytest.raises(BackupError, match="nothing to back up"):
        make_backup(tmp_path / "data", tmp_path / "backups")


def test_a_damaged_database_is_refused_rather_than_backed_up(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", rows=300)
    scribble(data / DATABASE)
    with pytest.raises(BackupError):
        make_backup(data, tmp_path / "backups", now=T0)
    assert not (tmp_path / "backups" / "quotex-20261102-093000" / DATABASE).exists()


def test_the_oldest_backups_are_pruned_and_only_ours(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data")
    into = tmp_path / "backups"
    for day in range(5):
        make_backup(data, into, now=T0 + timedelta(days=day), keep=100)
    (into / "my-own-folder").mkdir()
    (into / "quotex-not-a-backup").mkdir()  # no manifest: not made by this tool
    gone = prune(into, 3)
    assert sorted(p.name for p in gone) == ["quotex-20261102-093000", "quotex-20261103-093000"]
    left = sorted(p.name for p in into.iterdir())
    assert left == [
        "my-own-folder",
        "quotex-20261104-093000",
        "quotex-20261105-093000",
        "quotex-20261106-093000",
        "quotex-not-a-backup",
    ]
    with pytest.raises(BackupError):
        prune(into, 0)


def test_a_new_backup_prunes_by_default(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data")
    into = tmp_path / "backups"
    for day in range(4):
        make_backup(data, into, now=T0 + timedelta(days=day), keep=2)
    assert len([p for p in into.iterdir() if p.name.startswith(PREFIX)]) == 2


def test_restoring_puts_the_old_data_back_and_keeps_what_it_replaced(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", rows=3)
    backup = make_backup(data, tmp_path / "backups", now=T0).folder
    # life goes on: more trades, a new login, a leftover write-ahead log
    db = sqlite3.connect(data / DATABASE)
    db.execute("INSERT INTO trades (note) VALUES ('after the backup')")
    db.commit()
    db.close()
    (data / "telegram.session").write_text("NEWER-LOGIN", encoding="utf-8")
    (data / f"{DATABASE}-wal").write_bytes(b"stale")

    kept = restore(backup, data, now=T0 + timedelta(hours=1))

    assert notes(data / DATABASE) == ["trade 0", "trade 1", "trade 2"]
    assert (data / "telegram.session").read_text(encoding="utf-8") == "SECRET-TELEGRAM-LOGIN"
    assert not (data / f"{DATABASE}-wal").exists()  # belonged to the database put aside
    assert kept.name == "quotex.db.before-restore-20261102-103000"
    assert "after the backup" in notes(kept)  # the mistake can be undone


def test_restoring_something_that_is_not_a_backup_changes_nothing(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data")
    before = (data / DATABASE).read_bytes()
    empty = tmp_path / "not-a-backup"
    empty.mkdir()
    with pytest.raises(BackupError, match="not a backup"):
        restore(empty, data)
    assert (data / DATABASE).read_bytes() == before


def test_restoring_a_damaged_backup_changes_nothing(tmp_path: Path) -> None:
    data = make_data(tmp_path / "data", rows=300)
    backup = make_backup(data, tmp_path / "backups", now=T0).folder
    scribble(backup / DATABASE)
    before = (data / DATABASE).read_bytes()
    with pytest.raises(BackupError):
        restore(backup, data)
    assert (data / DATABASE).read_bytes() == before
    assert [p.name for p in data.iterdir() if "before-restore" in p.name] == []


def test_a_restore_into_an_empty_data_folder_works_too(tmp_path: Path) -> None:
    backup = make_backup(make_data(tmp_path / "old"), tmp_path / "backups", now=T0).folder
    new_data = tmp_path / "brand-new-machine" / "data"
    kept = restore(backup, new_data, now=T0)
    assert notes(new_data / DATABASE) == ["trade 0", "trade 1", "trade 2"]
    assert not kept.exists()  # there was nothing to put aside
