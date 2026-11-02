// Plain-language wording for the reports, so the numbers are never shown without what they mean.
import type { ReportSummary } from '../api/types'
import { formatPercent } from './format'

export type Sample = 'tiny' | 'small' | 'ok'

/** What a sample size means for how far to trust a percentage. */
export function sampleNote(sample: Sample, trades: number): string | null {
  if (sample === 'tiny') {
    return `Only ${String(trades)} trades: far too few to conclude anything. Luck alone can explain almost any result.`
  }
  if (sample === 'small') {
    return `${String(trades)} trades: a small sample. Treat these figures as a hint, not a result.`
  }
  return null
}

export function sampleLabel(sample: Sample): string {
  return sample === 'tiny'
    ? 'too few trades'
    : sample === 'small'
      ? 'small sample'
      : 'enough trades'
}

export interface Reading {
  headline: string
  detail: string
}

/**
 * "Is this really working?" in words. A trade at payout p wins back p% of its stake and loses all of
 * it, so it breaks even when it wins 1/(1+p) of the time. No staking system changes that: only the
 * win rate decides, and only a long record can show whether it is above chance.
 */
export function readExpectation(summary: ReportSummary): Reading {
  const e = summary.expectation
  const trades = summary.metrics.trades
  if (e.breakeven_win_rate === null || e.actual_win_rate === null || e.edge === null) {
    return { headline: 'No finished trades in this range yet.', detail: 'Nothing to compare.' }
  }
  const compare = `At the average payout of ${(summary.metrics.avg_payout_pct ?? 0).toFixed(1)}%, a trade has to win ${formatPercent(e.breakeven_win_rate)} of the time just to break even. These trades won ${formatPercent(e.actual_win_rate)}, which is ${formatPercent(Math.abs(e.edge))} ${e.edge >= 0 ? 'above' : 'below'} that line.`
  switch (e.verdict) {
    case 'not_enough_data':
      return {
        headline: `Not enough trades to tell (${String(trades)}).`,
        detail: `${compare} With this few trades the difference could easily be luck. Wait for at least ${String(summary.sample_guide.small_below)} finished trades, and preferably a few hundred.`,
      }
    case 'consistent_with_break_even':
      return {
        headline: 'Indistinguishable from break-even so far.',
        detail: `${compare} That gap is within what luck produces (${(e.z_score ?? 0).toFixed(1)} standard errors). It does not show an advantage, and it does not rule one out.`,
      }
    case 'above_break_even':
      return {
        headline: 'Above break-even, beyond what luck usually explains.',
        detail: `${compare} That is ${(e.z_score ?? 0).toFixed(1)} standard errors above the line. Promising: confirm it holds on more trades and on the real account's payouts before trusting it.`,
      }
    case 'below_break_even':
      return {
        headline: 'Below break-even, beyond what luck usually explains.',
        detail: `${compare} That is ${Math.abs(e.z_score ?? 0).toFixed(1)} standard errors below the line: on this record the strategy loses money on average, whatever the staking.`,
      }
  }
}
