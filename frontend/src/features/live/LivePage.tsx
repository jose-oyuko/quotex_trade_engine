import { useSignals, useStatus } from '../../api/queries'
import { DataState } from '../../components/DataState'
import { SignalsTable } from '../signals/SignalsTable'
import { ChainsPanel } from './ChainsPanel'
import { OpenTradesPanel } from './OpenTradesPanel'
import { StatsPanel } from './StatsPanel'

export default function LivePage() {
  const status = useStatus()
  const recent = useSignals({ limit: 8, offset: 0 })
  return (
    <section aria-labelledby="live-heading">
      <h1 id="live-heading">Live</h1>
      <DataState query={status}>
        {(snapshot) => (
          <>
            {!snapshot.engine.running && (
              <p className="notice" role="status">
                The trading engine is not running, so nothing is traded and no signals are read. Set{' '}
                <code>ENGINE_ENABLED=true</code> in <code>backend/.env</code> and restart the
                backend to start it. You can still set up groups and limits.
              </p>
            )}
            <StatsPanel />
            <h2>Chains running</h2>
            <ChainsPanel chains={snapshot.open_chains} />
            <h2>Trades open</h2>
            <OpenTradesPanel trades={snapshot.open_trades} />
            <h2>Latest messages</h2>
            <DataState query={recent} isEmpty={(page) => page.total === 0} empty="No messages yet.">
              {(page) => <SignalsTable signals={page.items} />}
            </DataState>
          </>
        )}
      </DataState>
    </section>
  )
}
