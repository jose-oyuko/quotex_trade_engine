import { NavLink, Outlet } from 'react-router-dom'
import { useStatus } from '../api/queries'
import type { Snapshot } from '../api/types'
import { Badge, type Tone } from '../components/Badge'
import { AccountBadge } from '../features/controls/AccountBadge'
import { KillSwitch } from '../features/controls/KillSwitch'
import { useLiveStatus } from '../live/liveStatus'
import { ErrorBoundary } from './ErrorBoundary'

const NAV = [
  { to: '/', label: 'Live', end: true },
  { to: '/signals', label: 'Signals', end: false },
  { to: '/groups', label: 'Groups', end: false },
  { to: '/history', label: 'History', end: false },
  { to: '/reports', label: 'Reports', end: false },
]

function Connection({ name, status }: { name: string; status: Snapshot }) {
  const connection = status.connections[name.toLowerCase()]
  let tone: Tone = 'muted'
  let text = 'not running'
  if (status.engine.running) {
    if (connection === undefined) {
      tone = 'warn'
      text = 'waiting'
    } else if (connection.connected) {
      tone = 'good'
      text = 'connected'
    } else {
      tone = 'bad'
      text = 'disconnected'
    }
  }
  return (
    <Badge tone={tone} title={connection?.detail ?? undefined}>
      {name}: {text}
    </Badge>
  )
}

function FeedBadge() {
  const live = useLiveStatus()
  const tone: Tone = live === 'live' ? 'good' : live === 'stopped' ? 'muted' : 'warn'
  const text = live === 'live' ? 'live' : live === 'stopped' ? 'stopped' : 'reconnecting…'
  return <Badge tone={tone}>Feed: {text}</Badge>
}

export function Layout() {
  const { data: status, isError } = useStatus()
  const real = status?.account_type === 'real'
  return (
    <>
      {real && (
        <div className="real-banner" role="alert">
          You are connected to your REAL MONEY account. Trades placed now use real funds.
        </div>
      )}
      <header className="topbar">
        <div className="brand">Quotex Trade Engine</div>
        <nav aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-status">
          {status ? (
            <>
              <AccountBadge account={status.account_type} />
              <Connection name="Telegram" status={status} />
              <Connection name="Quotex" status={status} />
            </>
          ) : (
            <Badge tone={isError ? 'bad' : 'muted'}>
              {isError ? 'Backend not reachable' : 'Account: loading…'}
            </Badge>
          )}
          <FeedBadge />
          <KillSwitch />
        </div>
      </header>
      <main>
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  )
}
