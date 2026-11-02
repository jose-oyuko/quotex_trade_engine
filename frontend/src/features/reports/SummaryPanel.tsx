import type { ReportSummary } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { Money } from '../../components/Money'
import { formatPercent } from '../../lib/format'
import { readExpectation, sampleLabel, sampleNote } from '../../lib/reportText'

const TONES: Record<ReportSummary['metrics']['sample'], Tone> = {
  tiny: 'bad',
  small: 'warn',
  ok: 'good',
}

function Card({
  label,
  children,
  note,
}: {
  label: string
  children: React.ReactNode
  note?: string
}) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{children}</dd>
      {note !== undefined && <small>{note}</small>}
    </div>
  )
}

/** The headline numbers, with how far to trust them stated right beside them. */
export function SummaryPanel({ summary }: { summary: ReportSummary }) {
  const m = summary.metrics
  const reading = readExpectation(summary)
  const caution = sampleNote(m.sample, m.trades)
  const { streaks, drawdown, not_counted: missing } = summary
  const plural = (n: number, one: string, many: string) => `${String(n)} ${n === 1 ? one : many}`
  const current =
    streaks.current === 0
      ? 'none'
      : streaks.current > 0
        ? `${plural(streaks.current, 'win', 'wins')} in a row`
        : `${plural(-streaks.current, 'loss', 'losses')} in a row`

  return (
    <section aria-labelledby="summary-heading">
      <h2 id="summary-heading">Summary</h2>
      <p>
        <Badge tone={TONES[m.sample]}>
          {sampleLabel(m.sample)}: {m.trades} finished trades
        </Badge>
      </p>
      {caution !== null && (
        <p className="notice" role="note">
          {caution}
        </p>
      )}
      <dl className="stats" aria-label="Report figures">
        <Card label="Profit">
          <Money value={m.profit} signed />
        </Card>
        <Card
          label="Win rate"
          note={`${String(m.wins)} won, ${String(m.losses)} lost${m.draws ? `, ${String(m.draws)} drawn` : ''}`}
        >
          {formatPercent(m.win_rate)}
        </Card>
        <Card label="Return on stakes" note={`on ${m.staked} staked`}>
          {formatPercent(m.roi)}
        </Card>
        <Card
          label="Biggest drawdown"
          note={
            drawdown.max_amount === '0.00'
              ? 'never below its high point'
              : `from ${drawdown.peak_day ?? 'the start'} to ${drawdown.trough_day ?? ''}`
          }
        >
          <Money value={drawdown.max_amount} />
        </Card>
        <Card label="Longest streaks" note={`now: ${current}`}>
          {streaks.longest_win} wins / {streaks.longest_loss} losses
        </Card>
        <Card label="Average payout">
          {m.avg_payout_pct === null ? '—' : `${m.avg_payout_pct.toFixed(1)}%`}
        </Card>
      </dl>
      {(missing.failed > 0 || missing.unknown > 0 || missing.open > 0) && (
        <p className="lead">
          Not counted in these figures (no known result): {missing.failed} failed, {missing.unknown}{' '}
          unknown, {missing.open} still open.
        </p>
      )}
      <div className="reading">
        <h3>Is it really working?</h3>
        <p>
          <strong>{reading.headline}</strong>
        </p>
        <p>{reading.detail}</p>
      </div>
    </section>
  )
}
