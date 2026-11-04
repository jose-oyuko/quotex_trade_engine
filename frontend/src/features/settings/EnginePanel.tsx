import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { EngineInfo, Snapshot } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'
import { PasswordConfirm } from './PasswordConfirm'

const STATE_TEXT: Record<EngineInfo['state'], { text: string; tone: Tone }> = {
  stopped: { text: 'Stopped', tone: 'muted' },
  starting: { text: 'Starting…', tone: 'warn' },
  running: { text: 'Running', tone: 'good' },
  stopping: { text: 'Stopping…', tone: 'warn' },
  failed: { text: 'Could not start', tone: 'bad' },
}

const SOURCE_TEXT: Record<EngineInfo['logins'][number]['source'], string> = {
  dashboard: 'stored here',
  '.env': 'from backend/.env',
  '.session file': 'from a login file (command line)',
  missing: 'missing',
  unreadable: 'stored, cannot be read',
}

function useRefresh() {
  const client = useQueryClient()
  return async () => {
    await Promise.all(
      [keys.engine, keys.status, keys.health, keys.risk].map((key) =>
        client.invalidateQueries({ queryKey: key }),
      ),
    )
  }
}

/** Start, stop and restart the engine, and see why it is not running. */
function EngineControls({ engine }: { engine: EngineInfo }) {
  const refresh = useRefresh()
  const [confirmStop, setConfirmStop] = useState(false)
  const run = useMutation({
    mutationFn: (action: 'start' | 'stop' | 'restart') => api.engine[action](),
    onSettled: refresh,
    onSuccess: () => {
      setConfirmStop(false)
    },
  })
  const running = engine.state === 'running'
  const busy = run.isPending || engine.state === 'starting' || engine.state === 'stopping'
  const missing = engine.missing_logins
  const status = STATE_TEXT[engine.state]

  return (
    <>
      <p>
        <strong>Trading engine:</strong> <Badge tone={status.tone}>{status.text}</Badge>
      </p>
      {engine.error !== null && (
        <p role="alert" className="form-error">
          {engine.error}
        </p>
      )}
      {run.isError && (
        <p role="alert" className="form-error">
          {errorMessage(run.error)}
        </p>
      )}
      <ul className="login-list">
        {engine.logins.map((login) => (
          <li key={login.label}>
            {login.label}:{' '}
            <Badge tone={login.present ? 'good' : login.required ? 'bad' : 'muted'}>
              {SOURCE_TEXT[login.source]}
            </Badge>
          </li>
        ))}
      </ul>
      {!running && missing.length > 0 && (
        <p className="help">
          Before it can start, add: {missing.join(', ')}. Store them below (or, for the Telegram API
          id, in <code>backend/.env</code>).
        </p>
      )}
      <div className="form-actions">
        {!running && (
          <Button
            variant="primary"
            disabled={busy || missing.length > 0}
            onClick={() => {
              run.mutate('start')
            }}
          >
            {engine.state === 'starting' ? 'Starting…' : 'Start the engine'}
          </Button>
        )}
        {running && (
          <>
            <Button
              disabled={busy}
              onClick={() => {
                run.mutate('restart')
              }}
            >
              Restart
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => {
                setConfirmStop(true)
              }}
            >
              Stop the engine
            </Button>
          </>
        )}
      </div>
      <p className="help">
        The engine always starts on the <strong>demo</strong> account. If you leave it running, it
        starts again by itself when the application starts.
      </p>
      {confirmStop && (
        <ConfirmDialog
          title="Stop the trading engine?"
          confirmLabel="Stop it"
          danger
          busy={run.isPending}
          error={run.isError ? errorMessage(run.error) : null}
          onConfirm={() => {
            run.mutate('stop')
          }}
          onCancel={() => {
            setConfirmStop(false)
            run.reset()
          }}
        >
          <p>
            No new signal will be traded. Trades that are open stay open on Quotex and run to their
            expiry, but here they are marked <em>unknown</em> straight away: look at them on Quotex.
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}

type Asking = 'allow' | 'disallow' | 'to-real' | null

/** Real-money trading: allowed only on purpose, and every step asks for the password again. */
function RealMoney({ engine, account }: { engine: EngineInfo; account: Snapshot['account_type'] }) {
  const refresh = useRefresh()
  const [asking, setAsking] = useState<Asking>(null)
  const change = useMutation({
    mutationFn: ({ kind, password }: { kind: Exclude<Asking, null>; password: string }) =>
      kind === 'to-real'
        ? api.account.set('real', password)
        : api.account.setRealTrading(kind === 'allow', password),
    onSettled: refresh,
    onSuccess: () => {
      setAsking(null)
    },
  })
  const close = () => {
    setAsking(null)
    change.reset()
  }
  const running = engine.state === 'running'
  const back = useMutation({ mutationFn: () => api.account.set('demo'), onSettled: refresh })

  return (
    <>
      <p>
        <strong>Account in use:</strong>{' '}
        <Badge tone={account === 'real' ? 'bad' : 'info'}>{account.toUpperCase()}</Badge>{' '}
        <strong>Real-money trading:</strong>{' '}
        <Badge tone={engine.real_trading_allowed ? 'warn' : 'muted'}>
          {engine.real_trading_allowed ? 'Allowed' : 'Not allowed'}
        </Badge>
      </p>
      {back.isError && (
        <p role="alert" className="form-error">
          {errorMessage(back.error)}
        </p>
      )}
      <div className="form-actions">
        {!engine.real_trading_allowed && (
          <Button
            onClick={() => {
              setAsking('allow')
            }}
          >
            Allow real-money trading…
          </Button>
        )}
        {engine.real_trading_allowed && account === 'demo' && (
          <Button
            variant="danger"
            disabled={!running}
            title={running ? undefined : 'Start the engine first'}
            onClick={() => {
              setAsking('to-real')
            }}
          >
            Switch to the REAL account…
          </Button>
        )}
        {account === 'real' && (
          <Button
            variant="primary"
            disabled={back.isPending}
            onClick={() => {
              back.mutate()
            }}
          >
            Switch back to the demo account
          </Button>
        )}
        {engine.real_trading_allowed && (
          <Button
            onClick={() => {
              setAsking('disallow')
            }}
          >
            Stop allowing real-money trading…
          </Button>
        )}
      </div>
      <p className="help">
        Until you allow it, nothing can use real money. Allowing it, and switching to the real
        account, each ask for your password again and are written to the risk log.
      </p>
      {asking !== null && (
        <PasswordConfirm
          title={
            asking === 'allow'
              ? 'Allow real-money trading?'
              : asking === 'disallow'
                ? 'Stop allowing real-money trading?'
                : 'Switch to the REAL account?'
          }
          confirmLabel={asking === 'to-real' ? 'Switch to REAL' : 'Confirm'}
          danger={asking !== 'disallow'}
          busy={change.isPending}
          error={change.error}
          onSubmit={(password) => {
            change.mutate({ kind: asking, password })
          }}
          onCancel={close}
        >
          <p>
            {asking === 'allow' &&
              'This only makes the switch to the REAL account possible; the account stays DEMO until you switch it yourself.'}
            {asking === 'disallow' && 'The REAL account can no longer be switched to.'}
            {asking === 'to-real' &&
              'From now on trades use REAL money. This is refused while a chain or trade is running.'}
          </p>
        </PasswordConfirm>
      )}
    </>
  )
}

export function EnginePanel({
  engine,
  account,
}: {
  engine: EngineInfo
  account: Snapshot['account_type']
}) {
  return (
    <fieldset>
      <legend>Trading engine</legend>
      <EngineControls engine={engine} />
      <hr />
      <RealMoney engine={engine} account={account} />
    </fieldset>
  )
}
