import { useRisk, useStatus, useTrades } from '../../api/queries'
import { Money } from '../../components/Money'
import { formatMs, median } from '../../lib/format'

function Stat({
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

/** The numbers at the top of the live page: balance, today's result, what is open, speed. */
export function StatsPanel() {
  const { data: status } = useStatus()
  const { data: risk } = useRisk()
  const recent = useTrades({ limit: 50, offset: 0 })
  if (status === undefined) return null

  const latencies = (recent.data?.items ?? [])
    .map((trade) => trade.latency.signal_to_order_ms)
    .filter((value): value is number => value !== null)
  const last = latencies[0] ?? null
  const account = status.account_type.toUpperCase()

  return (
    <dl className="stats" aria-label="Summary">
      <Stat label={`Balance (${account})`}>
        {status.balance ? <Money value={status.balance.balance} /> : '—'}
      </Stat>
      <Stat
        label="Today"
        note={risk?.day ? 'since the daily limits last reset' : 'engine not running'}
      >
        {risk?.day ? <Money value={risk.day.pnl} signed /> : '—'}
      </Stat>
      <Stat label="Chains running">{status.open_chains.length}</Stat>
      <Stat label="Trades open">{status.open_trades.length}</Stat>
      <Stat
        label="Signal to order"
        note={
          latencies.length > 0
            ? `latest order; median ${formatMs(median(latencies))} of the last ${String(latencies.length)}`
            : 'no trades yet'
        }
      >
        {formatMs(last)}
      </Stat>
    </dl>
  )
}
