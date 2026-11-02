import { useMemo, useState } from 'react'
import { reportCsvUrl, type ReportFilters } from '../../api/client'
import { useReportSummary, useStatus } from '../../api/queries'
import { DataState } from '../../components/DataState'
import { browserOffsetMinutes } from '../../lib/dates'
import { BreakdownPanel } from './BreakdownPanel'
import { DepthPanel } from './DepthPanel'
import { EquityPanel } from './EquityPanel'
import { FilterBar, type ReportControls } from './FilterBar'
import { toFilters } from './filters'
import { SummaryPanel } from './SummaryPanel'

function Downloads({ filters }: { filters: ReportFilters }) {
  const [delimiter, setDelimiter] = useState<'comma' | 'semicolon'>('comma')
  return (
    <section aria-labelledby="downloads-heading">
      <h2 id="downloads-heading">Download</h2>
      <p className="lead">
        Spreadsheet files for Excel (UTF-8). Every trade in the period, whatever its result, or the
        figures split by group, asset, strategy, hour or weekday.
      </p>
      <p>
        <label>
          Column separator{' '}
          <select
            value={delimiter}
            onChange={(event) => {
              setDelimiter(event.target.value as 'comma' | 'semicolon')
            }}
          >
            <option value="comma">Comma (,)</option>
            <option value="semicolon">Semicolon (;) if Excel shows one column</option>
          </select>
        </label>
      </p>
      <p className="actions-row">
        <a className="btn btn-default" href={reportCsvUrl('trades', filters, delimiter)} download>
          Download all trades (CSV)
        </a>
        {(['group', 'asset', 'strategy', 'hour', 'weekday'] as const).map((by) => (
          <a
            key={by}
            className="btn btn-default"
            href={reportCsvUrl(by, filters, delimiter)}
            download
          >
            By {by === 'hour' ? 'hour of day' : by} (CSV)
          </a>
        ))}
      </p>
    </section>
  )
}

export default function ReportsPage() {
  const { data: status } = useStatus()
  const [controls, setControls] = useState<ReportControls>({
    account: 'demo',
    range: { preset: 'all' },
    groupId: undefined,
    strategy: undefined,
    asset: '',
  })
  const offset = useMemo(() => browserOffsetMinutes(), [])
  const { filters, error } = useMemo(
    () => toFilters(controls, new Date(), offset),
    [controls, offset],
  )

  return (
    <section aria-labelledby="reports-heading">
      <h1 id="reports-heading">Reports</h1>
      <p className="lead">
        Is this really working? Demo and real money are never mixed: pick one. Finished trades only
        count; the figures say how many there are, because a short record proves nothing.
        {status?.account_type === 'real' && ' (You are connected to the real account.)'}
      </p>
      <FilterBar value={controls} onChange={setControls} rangeError={error} />
      {filters === null ? null : <Results filters={filters} />}
    </section>
  )
}

function Results({ filters }: { filters: ReportFilters }) {
  const summary = useReportSummary(filters)
  return (
    <>
      <DataState
        query={summary}
        isEmpty={(data) =>
          data.metrics.trades === 0 &&
          data.not_counted.failed + data.not_counted.unknown + data.not_counted.open === 0
        }
        empty="No trades in this period for this account. Change the period or the filters, or wait for the engine to trade."
      >
        {(data) => <SummaryPanel summary={data} />}
      </DataState>
      <EquityPanel filters={filters} />
      <BreakdownPanel filters={filters} />
      <DepthPanel filters={filters} />
      <Downloads filters={filters} />
    </>
  )
}
