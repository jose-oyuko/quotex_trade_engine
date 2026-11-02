import { useState } from 'react'
import type { ReportFilters } from '../../api/client'
import { useReportBreakdown } from '../../api/queries'
import type { BreakdownKind, ReportBreakdownRow } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { BarChart } from '../../components/charts/BarChart'
import { DataState } from '../../components/DataState'
import { Money } from '../../components/Money'
import { formatPercent } from '../../lib/format'
import { sampleLabel } from '../../lib/reportText'

const TABS: { by: BreakdownKind; label: string; chart: string }[] = [
  { by: 'group', label: 'By group', chart: 'Profit by group' },
  { by: 'asset', label: 'By asset', chart: 'Profit by asset' },
  { by: 'strategy', label: 'By strategy', chart: 'Profit by strategy' },
  { by: 'hour', label: 'By hour of day', chart: 'Profit by hour of day' },
  { by: 'weekday', label: 'By weekday', chart: 'Profit by weekday' },
]

const TONES: Record<ReportBreakdownRow['metrics']['sample'], Tone> = {
  tiny: 'bad',
  small: 'warn',
  ok: 'good',
}

const clip = (text: string) => (text.length > 14 ? `${text.slice(0, 13)}…` : text)

/** The same figures split five ways. Rows with too few trades are faded and labelled. */
export function BreakdownPanel({ filters }: { filters: ReportFilters }) {
  const [by, setBy] = useState<BreakdownKind>('group')
  const query = useReportBreakdown(by, filters)
  const tab = TABS.find((t) => t.by === by) ?? TABS[0]

  return (
    <section aria-labelledby="breakdown-heading">
      <h2 id="breakdown-heading">Where the result comes from</h2>
      <div role="tablist" aria-label="Split the report by" className="tabs">
        {TABS.map((t) => (
          <button
            key={t.by}
            role="tab"
            type="button"
            id={`tab-${t.by}`}
            aria-selected={t.by === by}
            aria-controls="breakdown-panel"
            className={t.by === by ? 'tab tab-active' : 'tab'}
            onClick={() => {
              setBy(t.by)
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="breakdown-panel" aria-labelledby={`tab-${by}`}>
        <DataState
          query={query}
          isEmpty={(data) => data.rows.every((row) => row.metrics.trades === 0)}
          empty="No finished trades in this range."
        >
          {(data) => (
            <>
              <BarChart
                label={tab?.chart ?? 'Profit'}
                signed
                format={(value) => value.toFixed(2)}
                bars={data.rows.map((row) => ({
                  label: by === 'hour' || by === 'weekday' ? row.label : clip(row.label),
                  value: Number(row.metrics.profit),
                  note: `${String(row.metrics.trades)} trades`,
                }))}
              />
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">{tab?.chart ?? 'Profit'}, with sample sizes</caption>
                  <thead>
                    <tr>
                      <th scope="col">
                        {by === 'hour' ? 'Hour' : by === 'weekday' ? 'Day' : 'Name'}
                      </th>
                      <th scope="col">Trades</th>
                      <th scope="col">Win rate</th>
                      <th scope="col">Profit</th>
                      <th scope="col">Return on stakes</th>
                      <th scope="col">Avg payout</th>
                      <th scope="col">Sample</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows
                      .filter((row) => by !== 'hour' || row.metrics.trades > 0)
                      .map((row) => (
                        <tr
                          key={row.key}
                          className={row.metrics.sample === 'tiny' ? 'row-faint' : undefined}
                        >
                          <th scope="row">{row.label}</th>
                          <td>{row.metrics.trades}</td>
                          <td>{formatPercent(row.metrics.win_rate)}</td>
                          <td>
                            <Money value={row.metrics.profit} signed />
                          </td>
                          <td>{formatPercent(row.metrics.roi)}</td>
                          <td>
                            {row.metrics.avg_payout_pct === null
                              ? '—'
                              : `${row.metrics.avg_payout_pct.toFixed(1)}%`}
                          </td>
                          <td>
                            {row.metrics.trades > 0 && (
                              <Badge tone={TONES[row.metrics.sample]}>
                                {sampleLabel(row.metrics.sample)}
                              </Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {by === 'hour' && (
                <p className="lead">Hours with no trades are left out of the table.</p>
              )}
            </>
          )}
        </DataState>
      </div>
    </section>
  )
}
