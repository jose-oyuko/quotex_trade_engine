"""CSV files that open correctly in Excel (decision D-47).

- **UTF-8 with a byte-order mark**, so Excel reads accents and symbols instead of guessing a legacy
  code page. (Plain UTF-8 without the mark opens as garbage in many Excel versions.)
- **Comma by default; semicolon on request.** Excel in many European locales uses `;` as its list
  separator and shows a comma file as one column, so the endpoint offers both.
- **Windows line endings** (CRLF), as Excel writes them.
- **Dot as the decimal separator** in money, always: `0.85`. (Excel in a comma-decimal locale shows
  these as text; the numbers are right and `;`-separated files do not change that.)
- **No formula injection.** A text cell that starts with `=`, `+`, `-`, `@`, tab or carriage return
  would be run as a formula by a spreadsheet; such cells get a leading apostrophe. Numbers are
  never touched (a loss like `-1.00` must stay a number).
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Iterable, Sequence
from enum import StrEnum

from app.reports.models import BreakdownRow, ExportRow

BOM = "﻿"
CRLF = "\r\n"
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class Delimiter(StrEnum):
    COMMA = "comma"
    SEMICOLON = "semicolon"

    @property
    def char(self) -> str:
        return "," if self is Delimiter.COMMA else ";"


def safe_text(value: str | None) -> str:
    """A text cell that a spreadsheet will show as text, whatever it says."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(FORMULA_STARTS) else value


def _line(cells: Sequence[object], delimiter: Delimiter) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter.char, lineterminator=CRLF).writerow(cells)
    return buffer.getvalue()


TRADE_COLUMNS = (
    "created_at_utc",
    "settled_at_utc",
    "account",
    "group_id",
    "group",
    "strategy",
    "asset",
    "direction",
    "step",
    "duration_s",
    "stake",
    "payout_pct",
    "status",
    "profit",
    "error",
    "trade_id",
    "chain_id",
)


def trade_cells(row: ExportRow) -> list[object]:
    return [
        row.created_at,
        row.settled_at,
        row.account_type,
        row.group_id,
        safe_text(row.group_title),
        row.strategy,
        safe_text(row.asset),
        row.direction,
        row.step,
        row.duration_s,
        row.stake,
        "" if row.payout_pct is None else row.payout_pct,
        row.status,
        row.profit,
        safe_text(row.error),
        row.trade_id,
        row.chain_id,
    ]


async def trades_csv(
    batches: AsyncIterator[list[ExportRow]], delimiter: Delimiter
) -> AsyncIterator[bytes]:
    """The file as chunks of bytes: the byte-order mark and header, then batches of rows."""
    yield (BOM + _line(TRADE_COLUMNS, delimiter)).encode("utf-8")
    async for batch in batches:
        buffer = io.StringIO()
        csv.writer(buffer, delimiter=delimiter.char, lineterminator=CRLF).writerows(
            trade_cells(row) for row in batch
        )
        yield buffer.getvalue().encode("utf-8")


BREAKDOWN_COLUMNS = (
    "key",
    "label",
    "trades",
    "wins",
    "losses",
    "draws",
    "win_rate",
    "profit",
    "staked",
    "roi",
    "avg_stake",
    "avg_payout_pct",
    "sample",
)


def breakdown_csv(rows: Iterable[BreakdownRow], delimiter: Delimiter) -> bytes:
    def number(value: float | None, digits: int) -> str:
        return "" if value is None else f"{value:.{digits}f}"

    lines = [BOM + _line(BREAKDOWN_COLUMNS, delimiter)]
    for row in rows:
        m = row.metrics
        lines.append(
            _line(
                [
                    safe_text(row.key),
                    safe_text(row.label),
                    m.trades,
                    m.wins,
                    m.losses,
                    m.draws,
                    number(m.win_rate, 4),
                    m.profit,
                    m.staked,
                    number(m.roi, 4),
                    "" if m.avg_stake is None else m.avg_stake,
                    number(m.avg_payout_pct, 1),
                    m.sample,
                ],
                delimiter,
            )
        )
    return "".join(lines).encode("utf-8")
