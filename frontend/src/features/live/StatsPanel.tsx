import { Fragment } from 'react'
import { useRisk, useStatus, useTrades } from '../../api/queries'
import { Money } from '../../components/Money'
import { BROKER_LABEL } from '../../lib/brokers'
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
  // With two brokers each has its own account and money: one balance and one day's result each,
  // never added up (decision D-75).
  const brokers = status.brokers ?? []
  const day = risk?.day ?? null

  return (
    <dl className="stats" aria-label="Summary">
      {brokers.length > 1 ? (
        brokers.map((broker) => {
          const balance = (status.balances ?? []).find((b) => b.broker === broker)
          const pnl = day?.by_broker?.[broker]
          return (
            <Fragment key={broker}>
              <Stat label={`${BROKER_LABEL[broker]} balance (${account})`}>
                {balance ? <Money value={balance.balance} /> : '—'}
              </Stat>
              <Stat
                label={`${BROKER_LABEL[broker]} today`}
                note={day ? 'since the daily limits last reset' : 'engine not running'}
              >
                {pnl !== undefined ? <Money value={pnl} signed /> : '—'}
              </Stat>
            </Fragment>
          )
        })
      ) : (
        <>
          <Stat
            label={brokers[0] === 'deriv' ? `Deriv balance (${account})` : `Balance (${account})`}
          >
            {status.balance ? <Money value={status.balance.balance} /> : '—'}
          </Stat>
          <Stat
            label="Today"
            note={day ? 'since the daily limits last reset' : 'engine not running'}
          >
            {day ? <Money value={day.pnl} signed /> : '—'}
          </Stat>
        </>
      )}
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
