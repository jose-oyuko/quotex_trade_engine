import { useEffect, useState } from 'react'
import { fetchHealth, type Health } from './api/health'

type State =
  { kind: 'loading' } | { kind: 'ok'; health: Health } | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then((health) => {
        setState({ kind: 'ok', health })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          kind: 'error',
          message: error instanceof Error ? error.message : 'Unknown error',
        })
      })
    return () => {
      controller.abort()
    }
  }, [])

  return (
    <main>
      <h1>Quotex Trade Engine</h1>
      <section aria-labelledby="health-heading">
        <h2 id="health-heading">Backend health</h2>
        {state.kind === 'loading' && <p role="status">Checking backend…</p>}
        {state.kind === 'error' && (
          <p role="alert" className="bad">
            Backend not reachable: {state.message}
          </p>
        )}
        {state.kind === 'ok' && (
          <p role="status" className="good">
            Health OK — version {state.health.version}, {state.health.environment}
          </p>
        )}
      </section>
    </main>
  )
}
