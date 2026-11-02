import { formatCountdown } from '../lib/format'
import { useNow } from './useNow'

/** Time left until `until` (an ISO time), as m:ss; "settling…" once it has passed. */
export function Countdown({ until }: { until: string | null }) {
  const now = useNow(1000)
  if (until === null) return <span>—</span>
  const left = (new Date(until).getTime() - now) / 1000
  if (Number.isNaN(left)) return <span>—</span>
  return left > 0 ? (
    <time dateTime={until} className="countdown">
      {formatCountdown(left)}
    </time>
  ) : (
    <span className="countdown countdown-late">settling…</span>
  )
}
