"""Find consolidations, breakouts and trends in stored prices (decision D-85), from the terminal.

    npm run market:scan -- --asset 1HZ75V --from 2026-11-12 --to 2026-11-19
    npm run market:scan -- --asset 1HZ75V --from 2026-11-12 --to 2026-11-19 --length M5
    npm run market:scan -- --asset 1HZ75V --from 2026-11-12 --to 2026-11-19 --compare

Reads the prices downloaded for backtests (`data/history.db`); nothing is downloaded or traded.
`--compare` puts every pattern side by side, each with its default settings.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from pydantic import ValidationError

from app.backtest.store import PriceStore
from app.core.config import Settings
from app.market.detector import PATTERN_DEFAULTS, BreakBy, MarketRules, Pattern
from app.market.stats import BREAK_EVEN, DEEP, MarketStats, Rate, Spread, compare
from app.services.market import (
    MAX_SCAN_CANDLES,
    InvalidMarketError,
    load_candles,
    scan_stored,
    span,
)

NAMED_LENGTHS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}


def length(text: str) -> int:
    """`M1`, `M5`, `H1` ... or a number of seconds."""
    if text.upper() in NAMED_LENGTHS:
        return NAMED_LENGTHS[text.upper()]
    try:
        return int(text.removesuffix("s"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a candle length: {text}") from None


def moment(text: str) -> datetime:
    found = datetime.fromisoformat(text)
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _pct(rate: Rate) -> str:
    return f"{100 * rate.share:5.1f}% ({100 * rate.low:.1f}-{100 * rate.high:.1f}, n={rate.total})"


def _spread(s: Spread, unit: str) -> str:
    return (
        f"median {s.median:g} {unit}, average {s.mean:.1f}, middle half {s.q1:g}-{s.q3:g}, "
        f"longest {s.longest} (n={s.count})"
    )


def report(stats: MarketStats) -> str:
    return "\n".join(
        [
            f"candles: {stats.candles}; consolidations: {stats.consolidations} "
            f"({stats.breakouts} broke out); {100 * stats.in_consolidation:.1f}% of the time "
            "inside one",
            "candles until the next consolidation is found:",
            f"  after a breakout: {_spread(stats.trend_wait, 'candles')}",
            f"  from any candle:  {_spread(stats.any_wait, 'candles')}",
            f"the breakout's way (break-even at 88%: {100 * BREAK_EVEN:.1f}%):",
            f"  the next candle:      {_pct(stats.first_with)}",
            f"  all the trend's candles: {_pct(stats.trend_with)}",
            f"flip pairs that lost {stats.deep}+ trades in a row:",
            f"  started at any candle:         {_pct(stats.deep_any)}",
            f"  started while trending:        {_pct(stats.deep_trend)}",
            f"  started in a known consolidation: {_pct(stats.deep_consolidation)}",
            f"those deep stretches inside a consolidation: {_pct(stats.described)}",
        ]
    )


def table(rows: list[tuple[MarketRules, MarketStats]]) -> str:
    head = (
        f"{'pattern':26}{'found':>7}{'inside':>8}{'describes':>11}"
        f"{'deep any':>10}{'trending':>10}{'in cons':>9}{'wait after':>12}{'wait any':>10}"
    )
    lines = [head]
    for rules, s in rows:
        lines.append(
            f"{_rules(rules):26}{s.consolidations:>7}{100 * s.in_consolidation:>7.1f}%"
            f"{100 * s.described.share:>10.1f}%{100 * s.deep_any.share:>9.2f}%"
            f"{100 * s.deep_trend.share:>9.2f}%{100 * s.deep_consolidation.share:>8.2f}%"
            f"{s.trend_wait.median:>12g}{s.any_wait.median:>10g}"
        )
    return "\n".join(lines)


def _rules(rules: MarketRules) -> str:
    extra = {
        Pattern.MIXED: f", {rules.misses} miss",
        Pattern.TIGHT: f", x{rules.width:g}",
        Pattern.CHOPPY: f", net {rules.net_share:g}",
    }.get(rules.pattern, "")
    return f"{rules.pattern.value} {rules.candles}{extra}"


def main(argv: list[str], settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset", required=True)
    parser.add_argument("--from", dest="start", type=moment, required=True)
    parser.add_argument("--to", dest="end", type=moment, required=True)
    parser.add_argument("--length", type=length, default=60, help="M1, M5, H1 or seconds")
    parser.add_argument("--pattern", choices=[p.value for p in Pattern], default="alternating")
    parser.add_argument("--candles", type=int, help="candles in the pattern")
    parser.add_argument("--misses", type=int, help="mixed: candles that may not alternate")
    parser.add_argument("--width", type=float, help="tight: times the average candle")
    parser.add_argument("--net-share", type=float, help="choppy: largest net move share")
    parser.add_argument("--breakout-candles", type=int, default=2)
    parser.add_argument("--breakout-by", choices=[b.value for b in BreakBy], default="close")
    parser.add_argument("--deep", type=int, default=DEEP, help="trades lost in a row")
    parser.add_argument("--compare", action="store_true", help="every pattern side by side")
    args = parser.parse_args(argv)
    if settings is None:
        try:
            settings = Settings()
        except ValidationError as exc:
            sys.stderr.write(f"Invalid configuration:\n{exc}\n")
            return 2
    store = PriceStore(settings.history_path)
    try:
        first, last = span(args.start, args.end, args.length, MAX_SCAN_CANDLES)
        if args.compare:
            candles = load_candles(store, args.asset, first, last, args.length)
            if not candles:
                raise InvalidMarketError(f"No prices of {args.asset} are stored in that period.")
            print(f"{args.asset}, {args.length} s candles, {len(candles)} candles")
            print(table(compare(candles, args.length, deep=args.deep)))
            return 0
        base = PATTERN_DEFAULTS[Pattern(args.pattern)]
        rules = MarketRules(
            pattern=base.pattern,
            candles=args.candles or base.candles,
            misses=base.misses if args.misses is None else args.misses,
            width=args.width or base.width,
            net_share=args.net_share or base.net_share,
            breakout_candles=args.breakout_candles,
            breakout_by=BreakBy(args.breakout_by),
        )
        found = scan_stored(store, args.asset, first, last, args.length, rules, args.deep)
    except (InvalidMarketError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    print(
        f"{args.asset}, {args.length} s candles, {_rules(rules)}, breakout: "
        f"{rules.breakout_candles} by {rules.breakout_by.value}"
    )
    print(report(found.stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
