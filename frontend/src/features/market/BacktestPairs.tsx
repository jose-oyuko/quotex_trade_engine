// Where a backtest's pairs were opened (Phase 31): choose a finished backtest of this asset and one
// of its runs, and the chart marks each pair on the candle it opened in, by what it made.
import { useBacktest, useBacktests } from '../../api/queries'
import type { BacktestPairs as Pairs } from '../../api/types'
import { runLabel } from '../backtest/backtestSchema'

export interface ShownBacktest {
  id: number
  run: number
}

function RunPicker({
  id,
  run,
  onChange,
}: {
  id: number
  run: number
  onChange: (run: number) => void
}) {
  const runs = useBacktest(id).data?.summary?.strategies ?? []
  if (runs.length < 2) return null
  return (
    <label>
      Run{' '}
      <select
        value={run}
        onChange={(e) => {
          onChange(Number(e.target.value))
        }}
      >
        {runs.map((r, i) => (
          <option key={i} value={i}>
            {runLabel(r, runs)}
          </option>
        ))}
      </select>
    </label>
  )
}

export function BacktestPairs({
  asset,
  shown,
  onShow,
  pairs,
}: {
  asset: string
  shown: ShownBacktest | null
  onShow: (shown: ShownBacktest | null) => void
  pairs: Pairs | undefined
}) {
  const done = (useBacktests().data?.items ?? []).filter(
    (b) => b.asset === asset && b.state === 'done',
  )
  if (done.length === 0) return null
  return (
    <section aria-labelledby="pairs-heading">
      <h2 id="pairs-heading">A backtest’s pairs</h2>
      <div className="filters">
        <label>
          Backtest{' '}
          <select
            value={shown?.id ?? ''}
            onChange={(e) => {
              onShow(e.target.value === '' ? null : { id: Number(e.target.value), run: 0 })
            }}
          >
            <option value="">none</option>
            {done.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        {shown !== null && (
          <RunPicker
            id={shown.id}
            run={shown.run}
            onChange={(run) => {
              onShow({ ...shown, run })
            }}
          />
        )}
      </div>
      {shown !== null && pairs !== undefined && (
        <p className="help" role="status">
          {pairs.items.length < pairs.total
            ? `The first ${pairs.items.length.toLocaleString()} of ${pairs.total.toLocaleString()} pairs`
            : `${pairs.total.toLocaleString()} pairs`}{' '}
          marked on the candle they opened in: green circle, the pair made money; red circle, it
          lost; red square, a leg lost every step.
        </p>
      )}
    </section>
  )
}
