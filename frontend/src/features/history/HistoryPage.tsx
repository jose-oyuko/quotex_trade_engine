import { useState } from 'react'
import { useGroups, useTrades } from '../../api/queries'
import type { AccountType, Trade, TradeStatus } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { DataState } from '../../components/DataState'
import { Money } from '../../components/Money'
import { Pagination } from '../../components/Pagination'
import { formatDateTime, formatMs, titleCase } from '../../lib/format'
import { useGroupNames } from '../controls/useGroupNames'

const STATUSES: TradeStatus[] = ['won', 'lost', 'draw', 'open', 'pending', 'failed', 'unknown']
const TONES: Record<TradeStatus, Tone> = {
  won: 'good',
  lost: 'bad',
  draw: 'muted',
  open: 'info',
  pending: 'info',
  failed: 'warn',
  unknown: 'warn',
}

function TradesTable({ trades }: { trades: Trade[] }) {
  const groupName = useGroupNames()
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Trade history, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Account</th>
            <th scope="col">Group</th>
            <th scope="col">Asset</th>
            <th scope="col">Direction</th>
            <th scope="col">Step</th>
            <th scope="col">Stake</th>
            <th scope="col">Payout</th>
            <th scope="col">Result</th>
            <th scope="col">Profit</th>
            <th scope="col">Order sent after</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td>{formatDateTime(trade.created_at)}</td>
              <td>
                <Badge tone={trade.account_type === 'real' ? 'bad' : 'info'}>
                  {trade.account_type.toUpperCase()}
                </Badge>
              </td>
              <td>{groupName(trade.group_id)}</td>
              <td>{trade.asset}</td>
              <td>{trade.direction.toUpperCase()}</td>
              <td>{trade.step + 1}</td>
              <td>
                <Money value={trade.stake} />
              </td>
              <td>{trade.payout_pct === null ? '—' : `${String(trade.payout_pct)}%`}</td>
              <td>
                <Badge tone={TONES[trade.status]} title={trade.error ?? undefined}>
                  {titleCase(trade.status)}
                </Badge>
              </td>
              <td>
                <Money value={trade.profit} signed />
              </td>
              <td>
                {formatMs(trade.latency.signal_to_order_ms ?? trade.latency.decision_to_order_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function HistoryPage() {
  const [groupId, setGroupId] = useState<number | undefined>(undefined)
  const [status, setStatus] = useState<TradeStatus | undefined>(undefined)
  const [account, setAccount] = useState<AccountType | undefined>(undefined)
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const groups = useGroups()
  const trades = useTrades({ limit, offset, group_id: groupId, status, account_type: account })

  const reset = (apply: () => void) => {
    apply()
    setOffset(0)
  }

  return (
    <section aria-labelledby="history-heading">
      <h1 id="history-heading">Trade history</h1>
      <div className="filters">
        <label>
          Group{' '}
          <select
            value={groupId ?? ''}
            onChange={(event) => {
              reset(() => {
                setGroupId(event.target.value === '' ? undefined : Number(event.target.value))
              })
            }}
          >
            <option value="">All groups</option>
            {(groups.data?.items ?? []).map((group) => (
              <option key={group.id} value={group.id}>
                {group.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Result{' '}
          <select
            value={status ?? ''}
            onChange={(event) => {
              reset(() => {
                setStatus(
                  event.target.value === '' ? undefined : (event.target.value as TradeStatus),
                )
              })
            }}
          >
            <option value="">All</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Account{' '}
          <select
            value={account ?? ''}
            onChange={(event) => {
              reset(() => {
                setAccount(
                  event.target.value === '' ? undefined : (event.target.value as AccountType),
                )
              })
            }}
          >
            <option value="">Demo and real</option>
            <option value="demo">Demo</option>
            <option value="real">Real</option>
          </select>
        </label>
      </div>
      <DataState
        query={trades}
        isEmpty={(page) => page.total === 0}
        empty="No trades match. Trades appear here as soon as the engine places them."
      >
        {(page) => (
          <>
            <TradesTable trades={page.items} />
            <Pagination
              offset={offset}
              limit={limit}
              total={page.total}
              onChange={setOffset}
              onLimitChange={(next) => {
                reset(() => {
                  setLimit(next)
                })
              }}
            />
          </>
        )}
      </DataState>
    </section>
  )
}
