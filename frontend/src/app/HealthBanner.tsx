import { useHealth } from '../api/queries'

/**
 * Says at the top of every page when something is wrong that the owner must know: the backend
 * cannot be reached, or it reports a problem (database, lost history, Quotex or Telegram
 * disconnected). Nothing is drawn while all is well.
 */
export function HealthBanner() {
  const health = useHealth()
  if (health.isError) {
    return (
      <div className="health-banner" role="alert">
        <strong>Cannot reach the backend.</strong> What you see may be out of date. Is it running?
      </div>
    )
  }
  const problems = health.data?.problems ?? []
  if (problems.length === 0) return null
  return (
    <div className="health-banner" role="alert">
      <strong>Attention:</strong>
      <ul>
        {problems.map((problem) => (
          <li key={problem}>{problem}</li>
        ))}
      </ul>
    </div>
  )
}
