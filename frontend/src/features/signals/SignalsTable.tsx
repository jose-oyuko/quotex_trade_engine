import type { Signal, SignalStatus } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { formatDateTime, titleCase } from '../../lib/format'
import { useGroupNames } from '../controls/useGroupNames'

const TONES: Record<SignalStatus, Tone> = { parsed: 'good', ignored: 'warn', not_parsed: 'muted' }

/**
 * The signal inbox. The message text comes from Telegram and is untrusted: React renders it as
 * plain text (never as HTML), and it is clipped in the table with the full text on hover.
 */
export function SignalsTable({ signals }: { signals: Signal[] }) {
  const groupName = useGroupNames()
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Messages received from the groups</caption>
        <thead>
          <tr>
            <th scope="col">Received</th>
            <th scope="col">Group</th>
            <th scope="col">Result</th>
            <th scope="col">Signal</th>
            <th scope="col">Why</th>
            <th scope="col">Message</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((signal) => (
            <tr key={signal.id}>
              <td>{formatDateTime(signal.received_at)}</td>
              <td>{groupName(signal.group_id)}</td>
              <td>
                <Badge tone={TONES[signal.status]}>{titleCase(signal.status)}</Badge>
              </td>
              <td>
                {signal.asset !== null && signal.direction !== null
                  ? `${signal.asset} ${signal.direction.toUpperCase()}${
                      signal.duration_s === null ? '' : ` ${String(signal.duration_s)}s`
                    }`
                  : '—'}
              </td>
              <td>{signal.reason ?? '—'}</td>
              <td className="clip" title={signal.raw_text}>
                {signal.raw_text}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
