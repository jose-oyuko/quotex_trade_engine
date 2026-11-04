import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { TelegramLoginStatus } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'

function Field({
  label,
  value,
  onChange,
  type = 'text',
  autoComplete = 'off',
  help,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'password'
  autoComplete?: string
  help?: string
}) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(event) => {
          onChange(event.target.value)
        }}
      />
      {help && <small className="help">{help}</small>}
    </div>
  )
}

/** Runs one step of the login and puts Telegram's answer in the cache. */
function useStep<A>(call: (arg: A) => Promise<TelegramLoginStatus>) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: call,
    onSuccess: (status) => {
      client.setQueryData(keys.telegramLogin, status)
      void client.invalidateQueries({ queryKey: keys.engine })
    },
  })
}

function Problem({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null
  return (
    <p role="alert" className="form-error">
      {errorMessage(error)}
    </p>
  )
}

/** Where the Telegram API id and hash are typed (they come from my.telegram.org). */
function ApiCredentials({ onSaved, cancel }: { onSaved: () => void; cancel?: () => void }) {
  const client = useQueryClient()
  const [apiId, setApiId] = useState('')
  const [apiHash, setApiHash] = useState('')
  const save = useMutation({
    mutationFn: async () => {
      await api.secrets.set('telegram_api_id', apiId.trim())
      await api.secrets.set('telegram_api_hash', apiHash.trim())
    },
    onSuccess: async () => {
      setApiId('')
      setApiHash('')
      await Promise.all(
        [keys.telegramLogin, keys.secrets, keys.engine].map((key) =>
          client.invalidateQueries({ queryKey: key }),
        ),
      )
      onSaved()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit}>
      <p className="help">
        Telegram needs an <strong>API id</strong> and <strong>API hash</strong> that identify this
        program. Get them at <code>my.telegram.org</code>: log in with your phone number, open{' '}
        <em>API development tools</em>, and create an application (any name).
      </p>
      <Field label="Telegram API id" value={apiId} onChange={setApiId} help="A number." />
      <Field label="Telegram API hash" value={apiHash} onChange={setApiHash} type="password" />
      <Problem error={save.error} />
      <div className="form-actions">
        <Button
          type="submit"
          variant="primary"
          aria-label="Save the API id and hash"
          disabled={save.isPending || apiId.trim() === '' || apiHash.trim() === ''}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </Button>
        {cancel && <Button onClick={cancel}>Cancel</Button>}
      </div>
    </form>
  )
}

function PhoneStep({ status }: { status: TelegramLoginStatus }) {
  const [phone, setPhone] = useState('')
  const start = useStep((value: string) => api.telegram.login.start(value))
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        start.mutate(phone)
      }}
    >
      <Field
        label="Phone number"
        value={phone}
        onChange={setPhone}
        autoComplete="tel"
        help="The number of the Telegram account that is in the signal groups: plus, country code, then the number, with no leading 0 (for example +254712345678)."
      />
      <Problem error={start.error} />
      <div className="form-actions">
        <Button
          type="submit"
          variant="primary"
          disabled={start.isPending || phone.trim() === '' || status.engine_running}
        >
          {start.isPending ? 'Asking Telegram…' : 'Send me the code'}
        </Button>
      </div>
    </form>
  )
}

function CodeStep({ status }: { status: TelegramLoginStatus }) {
  const [code, setCode] = useState('')
  const check = useStep((value: string) => api.telegram.login.code(value))
  const resend = useStep(() => api.telegram.login.resend())
  const cancel = useStep(() => api.telegram.login.cancel())
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        check.mutate(code)
      }}
    >
      <p>
        Telegram sent a code to <strong>{status.phone_hint}</strong> {status.delivery}.
      </p>
      <Field label="Login code" value={code} onChange={setCode} help="Usually 5 digits." />
      <Problem error={check.error ?? resend.error ?? cancel.error} />
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={check.isPending || code.trim() === ''}>
          {check.isPending ? 'Checking…' : 'Check the code'}
        </Button>
        <Button
          disabled={resend.isPending || status.resends_left === 0}
          onClick={() => {
            resend.mutate(undefined)
          }}
        >
          Send it another way ({status.resends_left} left)
        </Button>
        <Button
          variant="quiet"
          disabled={cancel.isPending}
          onClick={() => {
            cancel.mutate(undefined)
          }}
        >
          Use another number
        </Button>
      </div>
    </form>
  )
}

function PasswordStep() {
  const [password, setPassword] = useState('')
  const send = useStep((value: string) => api.telegram.login.password(value))
  const cancel = useStep(() => api.telegram.login.cancel())
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        send.mutate(password)
      }}
    >
      <p>
        This Telegram account has <strong>two-step verification</strong>. Type its password (the one
        you chose in Telegram, not your phone's).
      </p>
      <Field
        label="Two-step verification password"
        type="password"
        value={password}
        onChange={setPassword}
        autoComplete="off"
      />
      <Problem error={send.error ?? cancel.error} />
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={send.isPending || password === ''}>
          {send.isPending ? 'Checking…' : 'Log in'}
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

function LoggedIn({ status }: { status: TelegramLoginStatus }) {
  const [asking, setAsking] = useState(false)
  const out = useStep(() => api.telegram.logout())
  return (
    <>
      <p>
        <Badge tone="good">Logged in</Badge> {status.phone_hint ?? ''}
      </p>
      {status.engine_running && (
        <p className="help">Stop the trading engine before logging out or in again.</p>
      )}
      <div className="form-actions">
        <Button
          variant="danger"
          disabled={status.engine_running}
          onClick={() => {
            setAsking(true)
          }}
        >
          Log out of Telegram…
        </Button>
      </div>
      {asking && (
        <ConfirmDialog
          title="Log out of Telegram?"
          confirmLabel="Log out"
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
            The stored login is deleted here and ended on Telegram's side. Signals are no longer
            read until you log in again (the API id and hash are kept, so you only need the phone
            number and the code).
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}

/** Telegram: the API id and hash, then the login (phone, code, and the password if there is one). */
export function TelegramPanel({ status }: { status: TelegramLoginStatus }) {
  const [editing, setEditing] = useState(false)
  return (
    <fieldset>
      <legend>Telegram</legend>
      {status.problem !== null && (
        <p role="alert" className="form-error">
          {status.problem}
        </p>
      )}
      {!status.configured || editing ? (
        <ApiCredentials
          onSaved={() => {
            setEditing(false)
          }}
          {...(status.configured
            ? {
                cancel: () => {
                  setEditing(false)
                },
              }
            : {})}
        />
      ) : (
        <>
          {status.state === 'logged_out' && <PhoneStep status={status} />}
          {status.state === 'code_sent' && <CodeStep status={status} />}
          {status.state === 'password_needed' && <PasswordStep />}
          {status.state === 'logged_in' && <LoggedIn status={status} />}
          {status.state !== 'code_sent' && status.state !== 'password_needed' && (
            <p className="help">
              API id and hash: stored.{' '}
              <Button
                variant="quiet"
                disabled={status.engine_running}
                onClick={() => {
                  setEditing(true)
                }}
              >
                Change them
              </Button>
            </p>
          )}
        </>
      )}
      <p className="help">
        Your login is kept encrypted in the database; it is as secret as a password. It is the
        session of <em>this program</em>: Telegram lists it among your devices, where you can also
        end it.
      </p>
    </fieldset>
  )
}
