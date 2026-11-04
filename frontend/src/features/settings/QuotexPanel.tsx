import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { QuotexLoginStatus } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'

/** Runs one step of the Quotex login and puts the answer in the cache. */
function useStep<A>(call: (arg: A) => Promise<QuotexLoginStatus>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: call,
    onSuccess: (status) => {
      client.setQueryData(keys.quotexLogin, status)
      void client.invalidateQueries({ queryKey: keys.engine })
    },
  })
}

function Problem({ error, message }: { error: unknown; message?: string | null }) {
  const text = error === null || error === undefined ? (message ?? null) : errorMessage(error)
  if (text === null) return null
  return (
    <p role="alert" className="form-error">
      {text}
    </p>
  )
}

function PinStep({ status }: { status: QuotexLoginStatus }) {
  const id = useId()
  const [pin, setPin] = useState('')
  const send = useStep((value: string) => api.quotex.login.pin(value))
  const cancel = useStep(() => api.quotex.login.cancel())
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        send.mutate(pin)
      }}
    >
      <p>
        Quotex wants to confirm this login. {status.pin_prompt ?? 'Enter the PIN it e-mailed you'}.
      </p>
      <div className="field">
        <label htmlFor={id}>PIN from the e-mail</label>
        <input
          id={id}
          inputMode="numeric"
          autoComplete="one-time-code"
          value={pin}
          onChange={(event) => {
            setPin(event.target.value)
          }}
        />
        <small className="help">Digits only. Check your spam folder if it does not arrive.</small>
      </div>
      <Problem error={send.error ?? cancel.error} />
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={send.isPending || pin.trim() === ''}>
          {send.isPending ? 'Checking…' : 'Send the PIN'}
        </Button>
        <Button
          variant="quiet"
          disabled={cancel.isPending}
          onClick={() => {
            cancel.mutate(undefined)
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  )
}

function LoggedOut({ status }: { status: QuotexLoginStatus }) {
  const start = useStep(() => api.quotex.login.start())
  return (
    <>
      <Problem error={start.error} message={status.message} />
      {!status.configured && (
        <p className="help">Store your Quotex email and password above first.</p>
      )}
      <div className="form-actions">
        <Button
          variant="primary"
          disabled={start.isPending || !status.configured || status.engine_running}
          onClick={() => {
            start.mutate(undefined)
          }}
        >
          {start.isPending ? 'Logging in…' : 'Log in to Quotex'}
        </Button>
      </div>
      {status.engine_running && <p className="help">Stop the trading engine before logging in.</p>}
      <p className="help">
        The first time (or from a new place), Quotex e-mails you a PIN: this box then asks for it.
        Logging in uses your <strong>demo</strong> account.
      </p>
    </>
  )
}

function LoggedIn({ status }: { status: QuotexLoginStatus }) {
  const [asking, setAsking] = useState(false)
  const out = useStep(() => api.quotex.logout())
  return (
    <>
      <p>
        <Badge tone="good">Logged in</Badge> The login is stored encrypted; the engine uses it.
      </p>
      {status.engine_running && (
        <p className="help">Stop the trading engine before removing the login.</p>
      )}
      <div className="form-actions">
        <Button
          variant="danger"
          disabled={status.engine_running}
          onClick={() => {
            setAsking(true)
          }}
        >
          Remove the stored login…
        </Button>
      </div>
      {asking && (
        <ConfirmDialog
          title="Remove the stored Quotex login?"
          confirmLabel="Remove"
          danger
          busy={out.isPending}
          error={out.isError ? errorMessage(out.error) : null}
          onConfirm={() => {
            out.mutate(undefined, {
              onSuccess: () => {
                setAsking(false)
              },
            })
          }}
          onCancel={() => {
            setAsking(false)
            out.reset()
          }}
        >
          <p>
            Your email and password stay stored. The engine will log in with them, and Quotex may
            ask for a PIN again.
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}

/** The Quotex login: with the stored email and password, and the PIN Quotex e-mails when it asks. */
export function QuotexPanel({ status }: { status: QuotexLoginStatus }) {
  const cancel = useStep(() => api.quotex.login.cancel())
  return (
    <fieldset>
      <legend>Quotex login</legend>
      {status.state === 'logged_out' && <LoggedOut status={status} />}
      {status.state === 'working' && (
        <>
          <p role="status">Talking to Quotex…</p>
          <div className="form-actions">
            <Button
              disabled={cancel.isPending}
              onClick={() => {
                cancel.mutate(undefined)
              }}
            >
              Cancel
            </Button>
          </div>
        </>
      )}
      {status.state === 'pin_needed' && <PinStep status={status} />}
      {status.state === 'logged_in' && <LoggedIn status={status} />}
    </fieldset>
  )
}
