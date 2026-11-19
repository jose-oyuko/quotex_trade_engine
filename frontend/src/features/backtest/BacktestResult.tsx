import { useState, type ReactNode } from 'react'
import { useAssetNames, useBacktest, useBacktestChains } from '../../api/queries'
import type { Backtest, BacktestChain, StrategyResult } from '../../api/types'
import { Badge } from '../../components/Badge'
import { BarChart } from '../../components/charts/BarChart'
import { LineChart } from '../../components/charts/LineChart'
import { DataState } from '../../components/DataState'
import { Money } from '../../components/Money'
import { Pagination } from '../../components/Pagination'
import { assetLabel } from './assetNames'
import { STRATEGIES } from './backtestSchema'

const strategyLabel = (s: StrategyResult) => {
  const name = STRATEGIES.find((x) => x.value === s.strategy)?.label ?? s.strategy
  return s.max_steps === 0 ? name : `${name} ×${s.multipliers.join(', ')}`
}

const percent = (part: number, whole: number) =>
  whole === 0 ? '—' : `${((100 * part) / whole).toFixed(1)}%`

const STOPS: Record<string, string> = {
  window_ended: 'window ended',
  profit_target: 'profit target',
  loss_limit: 'loss limit',
  max_pairs: 'most pairs',
}

function Comparison({ strategies }: { strategies: StrategyResult[] }) {
  const rows: { label: string; cell: (s: StrategyResult) => ReactNode }[] = [
    { label: 'Profit', cell: (s) => <Money value={s.profit} signed /> },
    {
      label: 'Worst drawdown',
      cell: (s) => (
        <Money value={Number(s.worst_drawdown) > 0 ? `-${s.worst_drawdown}` : '0'} signed />
      ),
    },
    { label: 'Largest stake', cell: (s) => <Money value={s.largest_stake} /> },
    { label: 'Most money in play at once', cell: (s) => <Money value={s.most_in_play} /> },
    { label: 'Pairs', cell: (s) => s.pairs.toLocaleString() },
    { label: 'Chains', cell: (s) => s.chains.toLocaleString() },
    {
      label: 'Chains won',
      cell: (s) => {
        const won = s.won_at_step.reduce((a, b) => a + b, 0)
        return `${won.toLocaleString()} (${percent(won, s.chains)})`
      },
    },
    {
      label: 'Chains lost (every step)',
      cell: (s) => `${s.exhausted.toLocaleString()} (${percent(s.exhausted, s.chains)})`,
    },
    { label: 'Most chains lost in a row', cell: (s) => s.longest_losing_run },
    { label: 'Trades', cell: (s) => s.trades.toLocaleString() },
    { label: 'Trades won', cell: (s) => percent(s.trades_won, s.trades) },
    { label: 'Money staked', cell: (s) => <Money value={s.staked} /> },
    {
      label: 'Rounds skipped (too many open / no prices)',
      cell: (s) => `${String(s.skipped_rounds)} / ${String(s.no_data_rounds)}`,
    },
    {
      label: 'Windows ended by',
      cell: (s) =>
        Object.entries(s.stops)
          .map(([reason, n]) => `${STOPS[reason] ?? reason}: ${String(n)}`)
          .join(', '),
    },
  ]
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">The strategies compared</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">Figure</span>
            </th>
            {strategies.map((s, i) => (
              <th key={i} scope="col">
                {strategyLabel(s)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {strategies.map((s, i) => (
                <td key={i}>{row.cell(s)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StrategyCharts({ result }: { result: StrategyResult }) {
  const bars = [
    ...result.won_at_step.map((n, k) => ({ label: `won at step ${String(k)}`, value: n })),
    { label: 'lost every step', value: result.exhausted },
  ]
  return (
    <section aria-label={strategyLabel(result)}>
      <h3>{strategyLabel(result)}</h3>
      <LineChart
        label={`Running profit of ${strategyLabel(result)}`}
        format={(value) => value.toFixed(2)}
        points={result.equity.map((p) => ({
          label: p.at.slice(0, 16).replace('T', ' '),
          value: Number(p.profit),
        }))}
      />
      <BarChart label={`How the chains of ${strategyLabel(result)} ended`} bars={bars} />
    </section>
  )
}

function ChainRow({ chain }: { chain: BacktestChain }) {
  return (
    <tr>
      <td>{chain.started.slice(0, 19).replace('T', ' ')}</td>
      <td>{chain.pair_no}</td>
      <td>{chain.origin.toUpperCase()}</td>
      <td>
        <Badge
          tone={
            chain.status === 'completed' ? 'good' : chain.status === 'exhausted' ? 'bad' : 'muted'
          }
        >
          {chain.status === 'completed'
            ? `won at step ${String(chain.steps - 1)}`
            : chain.status === 'exhausted'
              ? 'lost every step'
              : 'no price data'}
        </Badge>
      </td>
      <td>
        <Money value={chain.profit} signed />
      </td>
      <td>
        <details>
          <summary>{chain.steps} trade(s)</summary>
          <ol>
            {chain.trades.map((t) => (
              <li key={t.start}>
                {t.start.slice(11, 19)} {t.direction.toUpperCase()} <Money value={t.stake} />:{' '}
                {t.entry} → {t.exit} <Money value={t.profit} signed />
              </li>
            ))}
          </ol>
        </details>
      </td>
    </tr>
  )
}

function Chains({ backtest }: { backtest: Backtest }) {
  const strategies = backtest.summary?.strategies ?? []
  const [strategy, setStrategy] = useState(0)
  const [status, setStatus] = useState<'' | 'completed' | 'exhausted' | 'failed'>('')
  const [offset, setOffset] = useState(0)
  const limit = 25
  const chains = useBacktestChains(backtest.id, {
    strategy,
    status: status === '' ? undefined : status,
    limit,
    offset,
  })
  return (
    <section aria-labelledby="chains-heading">
      <h2 id="chains-heading">The chains</h2>
      <div className="filters">
        <label>
          Strategy
          <select
            value={strategy}
            onChange={(e) => {
              setStrategy(Number(e.target.value))
              setOffset(0)
            }}
          >
            {strategies.map((s, i) => (
              <option key={i} value={i}>
                {strategyLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Ended
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as typeof status)
              setOffset(0)
            }}
          >
            <option value="">any way</option>
            <option value="completed">won</option>
            <option value="exhausted">lost every step</option>
            <option value="failed">no price data</option>
          </select>
        </label>
      </div>
      <DataState
        query={chains}
        isEmpty={(data) => data.items.length === 0}
        empty="No chain matches."
      >
        {(data) => (
          <>
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Chains of the backtest</caption>
                <thead>
                  <tr>
                    <th scope="col">Started (UTC)</th>
                    <th scope="col">Pair</th>
                    <th scope="col">Leg</th>
                    <th scope="col">Ended</th>
                    <th scope="col">Result</th>
                    <th scope="col">Trades</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((chain) => (
                    <ChainRow
                      key={`${String(chain.strategy)}-${String(chain.seq)}`}
                      chain={chain}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination offset={offset} limit={limit} total={data.total} onChange={setOffset} />
          </>
        )}
      </DataState>
    </section>
  )
}

export function BacktestResult({ id }: { id: number }) {
  const query = useBacktest(id)
  const names = useAssetNames().data?.items ?? []
  return (
    <DataState query={query}>
      {(backtest) => {
        const setup = backtest.setup
        if (backtest.state === 'running') {
          const done = Math.round(backtest.progress * 100)
          return (
            <section className="run-panel" aria-live="polite">
              <h2>{backtest.name}</h2>
              <progress max={100} value={done} aria-label={`Backtest ${String(done)}% done`} />{' '}
              {done}%
            </section>
          )
        }
        if (backtest.summary === null) {
          return (
            <section className="run-panel">
              <h2>{backtest.name}</h2>
              <p role="alert" className="form-error">
                {backtest.state === 'cancelled'
                  ? 'This backtest was cancelled.'
                  : `This backtest failed: ${backtest.error ?? 'no reason given'}`}
              </p>
            </section>
          )
        }
        const summary = backtest.summary
        return (
          <section aria-labelledby="result-heading">
            <h2 id="result-heading">{backtest.name}</h2>
            <p className="notice" role="note">
              A backtest is not a prediction. It assumes a payout of {setup.payout_pct}% on every
              win (Deriv keeps no past payouts), an order delay of {setup.order_delay_s} s and a
              step delay of {setup.step_delay_s} s; network drops, missed steps and order refusals
              are not simulated.
            </p>
            <p className="help">
              {assetLabel(setup.asset, names)}, {setup.first_day} to {setup.last_day},{' '}
              {setup.start_time.slice(0, 5)}–{setup.end_time.slice(0, 5)} {setup.timezone},{' '}
              {String(setup.duration_s / 60)}-minute trades, base stake{' '}
              <Money value={setup.base_stake} />: {summary.windows} window(s), replayed in{' '}
              {summary.seconds} s.
            </p>
            <Comparison strategies={summary.strategies} />
            {summary.strategies.map((s, i) => (
              <StrategyCharts key={i} result={s} />
            ))}
            <Chains backtest={backtest} />
          </section>
        )
      }}
    </DataState>
  )
}
