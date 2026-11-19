"""The price store: past ticks and the downloads that fetched them (decision D-84).

A separate SQLite file (`data/history.db`), not the trading database: a month of a one-tick-a-second
index is millions of rows, and the trading database and its writer must stay small and quick.

Every method is plain blocking SQLite and opens its own connection, so callers run it in a worker
thread (`asyncio.to_thread`): the event loop never waits on this file.

Which seconds were downloaded is kept as ranges (`coverage`), apart from the ticks themselves: an
index that ticks every 2 s, or a market that was closed, has seconds without a tick, and the store
must still know they were asked for.
"""

from __future__ import annotations

import sqlite3
from array import array
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 2  # 2: backtests (Phase 27)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        ticks INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS ticks (
        asset_id INTEGER NOT NULL,
        epoch INTEGER NOT NULL,
        quote REAL NOT NULL,
        PRIMARY KEY (asset_id, epoch)
    ) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS coverage (
        asset_id INTEGER NOT NULL,
        start INTEGER NOT NULL,
        "end" INTEGER NOT NULL,
        PRIMARY KEY (asset_id, start)
    ) WITHOUT ROWID""",
    """CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset TEXT NOT NULL,
        start INTEGER NOT NULL,
        "end" INTEGER NOT NULL,
        state TEXT NOT NULL,
        ticks INTEGER NOT NULL DEFAULT 0,
        reached INTEGER,
        note TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS backtests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        state TEXT NOT NULL,
        progress REAL NOT NULL DEFAULT 0,
        setup TEXT NOT NULL,
        summary TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS backtest_chains (
        backtest_id INTEGER NOT NULL,
        strategy INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        day TEXT NOT NULL,
        pair_no INTEGER NOT NULL,
        origin TEXT NOT NULL,
        started INTEGER NOT NULL,
        status TEXT NOT NULL,
        steps INTEGER NOT NULL,
        profit TEXT NOT NULL,
        trades TEXT NOT NULL,
        PRIMARY KEY (backtest_id, strategy, seq)
    ) WITHOUT ROWID""",
)


@dataclass(slots=True, frozen=True)
class AssetHeld:
    asset: str
    ticks: int
    first: int | None  # the oldest stored tick (epoch seconds)
    last: int | None
    ranges: list[tuple[int, int]]  # the downloaded seconds, merged, oldest first


@dataclass(slots=True, frozen=True)
class DownloadRow:
    id: int
    asset: str
    start: int
    end: int
    state: str  # running, done, failed, cancelled
    ticks: int  # new ticks stored
    reached: int | None  # downloaded from here up to `end`
    note: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


ACTIVE_DOWNLOAD = "running"


class PriceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def prepare(self, now: datetime, *, cut_running: bool = True) -> int:
        """Create the file and tables if needed. With `cut_running` (the application, at start),
        a download still marked running was cut by a stop of the program: it is marked failed
        (what it stored is kept). Returns how many."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            for statement in _SCHEMA:
                db.execute(statement)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            if not cut_running:
                return 0
            cut = db.execute(
                "UPDATE downloads SET state='failed', error=?, finished_at=? WHERE state=?",
                ("The program stopped during the download.", now.isoformat(), ACTIVE_DOWNLOAD),
            ).rowcount
            cut += db.execute(
                "UPDATE backtests SET state='failed', error=?, finished_at=? WHERE state=?",
                ("The program stopped during the backtest.", now.isoformat(), ACTIVE_DOWNLOAD),
            ).rowcount
        return int(cut)

    # ---- ticks -------------------------------------------------------------------------------

    @staticmethod
    def _asset_id(db: sqlite3.Connection, asset: str, *, create: bool) -> int | None:
        row = db.execute("SELECT id FROM assets WHERE name=?", (asset,)).fetchone()
        if row is not None:
            return int(row[0])
        if not create:
            return None
        return int(db.execute("INSERT INTO assets (name) VALUES (?)", (asset,)).lastrowid or 0)

    def add(self, asset: str, times: Sequence[int], quotes: Sequence[float]) -> int:
        """Store ticks (ones already held are kept as they are). Returns how many were new."""
        with self._db() as db:
            asset_id = self._asset_id(db, asset, create=True)
            added = db.executemany(
                "INSERT OR IGNORE INTO ticks (asset_id, epoch, quote) VALUES (?, ?, ?)",
                ((asset_id, t, q) for t, q in zip(times, quotes, strict=True)),
            ).rowcount
            db.execute("UPDATE assets SET ticks = ticks + ? WHERE id=?", (added, asset_id))
        return int(added)

    def load(self, asset: str, start: int, end: int) -> tuple[array[int], array[float]]:
        """The stored ticks of `asset` from `start` to `end` (both included), oldest first."""
        times: array[int] = array("q")
        quotes: array[float] = array("d")
        with self._db() as db:
            asset_id = self._asset_id(db, asset, create=False)
            if asset_id is None:
                return times, quotes
            rows = db.execute(
                "SELECT epoch, quote FROM ticks WHERE asset_id=? AND epoch BETWEEN ? AND ? "
                "ORDER BY epoch",
                (asset_id, start, end),
            )
            for epoch, quote in rows:
                times.append(epoch)
                quotes.append(quote)
        return times, quotes

    def forget(self, asset: str) -> bool:
        """Delete an asset's ticks and what was downloaded. False if none was held."""
        with self._db() as db:
            asset_id = self._asset_id(db, asset, create=False)
            if asset_id is None:
                return False
            db.execute("DELETE FROM ticks WHERE asset_id=?", (asset_id,))
            db.execute("DELETE FROM coverage WHERE asset_id=?", (asset_id,))
            db.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        return True

    # ---- what was downloaded -----------------------------------------------------------------

    def cover(self, asset: str, start: int, end: int) -> None:
        """Record that every second from `start` to `end` was downloaded."""
        if end < start:
            return
        with self._db() as db:
            asset_id = self._asset_id(db, asset, create=True)
            ranges = [*_ranges(db, asset_id), (start, end)]
            db.execute("DELETE FROM coverage WHERE asset_id=?", (asset_id,))
            db.executemany(
                'INSERT INTO coverage (asset_id, start, "end") VALUES (?, ?, ?)',
                ((asset_id, a, b) for a, b in merge(ranges)),
            )

    def coverage(self, asset: str) -> list[tuple[int, int]]:
        with self._db() as db:
            asset_id = self._asset_id(db, asset, create=False)
            return [] if asset_id is None else _ranges(db, asset_id)

    def missing(self, asset: str, start: int, end: int) -> list[tuple[int, int]]:
        """The parts of `start`..`end` not downloaded yet, oldest first."""
        return subtract((start, end), self.coverage(asset))

    def held(self) -> list[AssetHeld]:
        with self._db() as db:
            assets = db.execute("SELECT id, name, ticks FROM assets ORDER BY name").fetchall()
            found: list[AssetHeld] = []
            for asset_id, name, ticks in assets:
                first, last = db.execute(
                    "SELECT MIN(epoch), MAX(epoch) FROM ticks WHERE asset_id=?", (asset_id,)
                ).fetchone()
                found.append(AssetHeld(name, int(ticks), first, last, _ranges(db, asset_id)))
        return found

    # ---- downloads ---------------------------------------------------------------------------

    def new_download(self, asset: str, start: int, end: int, now: datetime) -> DownloadRow:
        with self._db() as db:
            download_id = db.execute(
                'INSERT INTO downloads (asset, start, "end", state, created_at) '
                "VALUES (?, ?, ?, ?, ?)",
                (asset, start, end, ACTIVE_DOWNLOAD, now.isoformat()),
            ).lastrowid
        found = self.download(int(download_id or 0))
        assert found is not None  # noqa: S101 - just written
        return found

    def update_download(
        self,
        download_id: int,
        *,
        state: str | None = None,
        ticks: int | None = None,
        reached: int | None = None,
        note: str | None = None,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        fields: dict[str, object] = {
            "state": state,
            "ticks": ticks,
            "reached": reached,
            "note": note,
            "error": error,
            "finished_at": finished_at.isoformat() if finished_at else None,
        }
        changes = {k: v for k, v in fields.items() if v is not None}
        if not changes:
            return
        assignments = ", ".join(f"{k}=?" for k in changes)
        with self._db() as db:
            db.execute(
                f"UPDATE downloads SET {assignments} WHERE id=?",  # noqa: S608 - fixed names
                (*changes.values(), download_id),
            )

    def download(self, download_id: int) -> DownloadRow | None:
        with self._db() as db:
            row = db.execute(f"{_DOWNLOAD_SELECT} WHERE id=?", (download_id,)).fetchone()
        return None if row is None else _download(row)

    def downloads(self, limit: int = 50) -> list[DownloadRow]:
        with self._db() as db:
            rows = db.execute(f"{_DOWNLOAD_SELECT} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_download(row) for row in rows]


_DOWNLOAD_SELECT = (
    'SELECT id, asset, start, "end", state, ticks, reached, note, error, created_at, finished_at '
    "FROM downloads"
)


def _download(row: Sequence[object]) -> DownloadRow:
    (download_id, asset, start, end, state, ticks, reached, note, error, created, finished) = row
    return DownloadRow(
        id=int(str(download_id)),
        asset=str(asset),
        start=int(str(start)),
        end=int(str(end)),
        state=str(state),
        ticks=int(str(ticks)),
        reached=None if reached is None else int(str(reached)),
        note=None if note is None else str(note),
        error=None if error is None else str(error),
        created_at=datetime.fromisoformat(str(created)),
        finished_at=None if finished is None else datetime.fromisoformat(str(finished)),
    )


def _ranges(db: sqlite3.Connection, asset_id: int | None) -> list[tuple[int, int]]:
    rows = db.execute(
        'SELECT start, "end" FROM coverage WHERE asset_id=? ORDER BY start', (asset_id,)
    ).fetchall()
    return [(int(a), int(b)) for a, b in rows]


def merge(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Ranges of whole seconds joined where they overlap or touch, oldest first."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(r for r in ranges if r[1] >= r[0]):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract(span: tuple[int, int], held: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """The parts of `span` outside every range of `held`, oldest first."""
    start, end = span
    gaps: list[tuple[int, int]] = []
    cursor = start
    for a, b in merge(held):
        if b < cursor:
            continue
        if a > end:
            break
        if a > cursor:
            gaps.append((cursor, a - 1))
        cursor = max(cursor, b + 1)
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


# ---- backtests (Phase 27) ----------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BacktestRow:
    id: int
    name: str
    state: str  # running, done, failed, cancelled
    progress: float
    setup: str  # JSON
    summary: str | None  # JSON, once done
    error: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(slots=True, frozen=True)
class ChainRow:
    strategy: int
    seq: int
    day: str
    pair_no: int
    origin: str
    started: int
    status: str
    steps: int
    profit: str
    trades: str  # JSON


def _backtest(row: Sequence[object]) -> BacktestRow:
    (backtest_id, name, state, progress, setup, summary, error, created, finished) = row
    return BacktestRow(
        id=int(str(backtest_id)),
        name=str(name),
        state=str(state),
        progress=float(str(progress)),
        setup=str(setup),
        summary=None if summary is None else str(summary),
        error=None if error is None else str(error),
        created_at=datetime.fromisoformat(str(created)),
        finished_at=None if finished is None else datetime.fromisoformat(str(finished)),
    )


class BacktestStore(PriceStore):
    """The price store plus the backtests run on it (the same file)."""

    def new_backtest(self, name: str, setup: str, now: datetime) -> BacktestRow:
        with self._db() as db:
            backtest_id = db.execute(
                "INSERT INTO backtests (name, state, setup, created_at) VALUES (?, ?, ?, ?)",
                (name, ACTIVE_DOWNLOAD, setup, now.isoformat()),
            ).lastrowid
        found = self.backtest(int(backtest_id or 0))
        assert found is not None  # noqa: S101 - just written
        return found

    def update_backtest(
        self,
        backtest_id: int,
        *,
        state: str | None = None,
        progress: float | None = None,
        summary: str | None = None,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        fields: dict[str, object] = {
            "state": state,
            "progress": progress,
            "summary": summary,
            "error": error,
            "finished_at": finished_at.isoformat() if finished_at else None,
        }
        changes = {k: v for k, v in fields.items() if v is not None}
        if not changes:
            return
        assignments = ", ".join(f"{k}=?" for k in changes)
        with self._db() as db:
            db.execute(
                f"UPDATE backtests SET {assignments} WHERE id=?",  # noqa: S608 - fixed names
                (*changes.values(), backtest_id),
            )

    def backtest(self, backtest_id: int) -> BacktestRow | None:
        with self._db() as db:
            row = db.execute(
                "SELECT id, name, state, progress, setup, summary, error, created_at, "
                "finished_at FROM backtests WHERE id=?",
                (backtest_id,),
            ).fetchone()
        return None if row is None else _backtest(row)

    def backtests(self, limit: int = 50) -> list[BacktestRow]:
        """The latest backtests, newest first, without their (large) summaries."""
        with self._db() as db:
            rows = db.execute(
                "SELECT id, name, state, progress, setup, NULL, error, created_at, finished_at "
                "FROM backtests ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_backtest(row) for row in rows]

    def add_chains(self, backtest_id: int, chains: Sequence[ChainRow]) -> None:
        with self._db() as db:
            db.executemany(
                "INSERT INTO backtest_chains (backtest_id, strategy, seq, day, pair_no, origin, "
                "started, status, steps, profit, trades) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        backtest_id,
                        c.strategy,
                        c.seq,
                        c.day,
                        c.pair_no,
                        c.origin,
                        c.started,
                        c.status,
                        c.steps,
                        c.profit,
                        c.trades,
                    )
                    for c in chains
                ),
            )

    def chains(
        self,
        backtest_id: int,
        *,
        strategy: int | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ChainRow], int]:
        """A page of a backtest's chains in time order, and how many match."""
        where = ["backtest_id=?"]
        params: list[object] = [backtest_id]
        if strategy is not None:
            where.append("strategy=?")
            params.append(strategy)
        if status is not None:
            where.append("status=?")
            params.append(status)
        condition = " AND ".join(where)
        with self._db() as db:
            total = db.execute(
                f"SELECT COUNT(*) FROM backtest_chains WHERE {condition}",  # noqa: S608
                params,
            ).fetchone()[0]
            columns = "strategy, seq, day, pair_no, origin, started, status, steps, profit, trades"
            query = f"SELECT {columns} FROM backtest_chains WHERE {condition}"  # noqa: S608
            rows = db.execute(
                f"{query} ORDER BY strategy, seq LIMIT ? OFFSET ?", (*params, limit, offset)
            ).fetchall()
        return [ChainRow(*row) for row in rows], int(total)

    def delete_backtest(self, backtest_id: int) -> bool:
        with self._db() as db:
            db.execute("DELETE FROM backtest_chains WHERE backtest_id=?", (backtest_id,))
            return bool(db.execute("DELETE FROM backtests WHERE id=?", (backtest_id,)).rowcount)
