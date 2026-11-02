import type { Trade } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Countdown } from '../../components/Countdown'
import { Money } from '../../components/Money'
import { formatMs, titleCase } from '../../lib/format'
import { useGroupNames } from '../controls/useGroupNames'

/** Trades whose result is not known yet, each with a countdown to its expiry. */
export function OpenTradesPanel({ trades }: { trades: Trade[] }) {
  const groupName = useGroupNames()
  if (trades.length === 0) return <p className="state-empty">No trades are open.</p>
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Trades open now</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">Asset</th>
            <th scope="col">Direction</th>
            <th scope="col">Step</th>
            <th scope="col">Stake</th>
            <th scope="col">Status</th>
            <th scope="col">Time left</th>
            <th scope="col">Order sent after</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.id}>
              <td>{groupName(trade.group_id)}</td>
              <td>{trade.asset}</td>
              <td>
                <Badge tone={trade.direction === 'call' ? 'good' : 'bad'}>
                  {trade.direction.toUpperCase()}
                </Badge>
              </td>
              <td>{trade.step + 1}</td>
              <td>
                <Money value={trade.stake} />
              </td>
              <td>
                <Badge tone="info">{titleCase(trade.status)}</Badge>
              </td>
              <td>
                <Countdown until={trade.expires_at} />
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
