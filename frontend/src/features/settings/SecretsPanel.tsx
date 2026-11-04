import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { SecretItem, SecretsOut } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'

const KEY_PROBLEM: Record<'missing' | 'invalid', string> = {
  missing:
    'SECRET_KEY is not set in backend/.env, so nothing can be stored. Run `npm run key:create` ' +
    '(starting with `npm start` does it too), then restart the application.',
  invalid:
    'SECRET_KEY in backend/.env is not a valid key. If you have nothing stored that you need, run ' +
    '`npm run key:create` after removing that line, then restart the application.',
}

function StatusBadge({ item, keyOk }: { item: SecretItem; keyOk: boolean }) {
  if (!item.is_set) return <Badge>Not set</Badge>
  if (!keyOk || !item.readable) {
    return (
      <Badge tone="bad" title="SECRET_KEY is not the key it was stored with">
        Stored, cannot be read
      </Badge>
    )
  }
  return <Badge tone="good">Stored</Badge>
}

function SecretRow({ item, keyOk }: { item: SecretItem; keyOk: boolean }) {
  const client = useQueryClient()
  const id = useId()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [removing, setRemoving] = useState(false)
  const refresh = () => client.invalidateQueries({ queryKey: keys.secrets })
  const save = useMutation({
    mutationFn: () => api.secrets.set(item.name, value),
    onSuccess: async () => {
      setValue('') // it is never kept on the page
      setEditing(false)
      await refresh()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.secrets.remove(item.name),
    onSuccess: async () => {
      setRemoving(false)
      await refresh()
    },
  })

  return (
    <li className="secret-row">
      <div>
        <strong>{item.label}</strong> <StatusBadge item={item} keyOk={keyOk} />
        <small className="help">{item.help}</small>
      </div>
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            save.mutate()
          }}
        >
          <div className="field">
            <label htmlFor={id}>New value for {item.label}</label>
            <input
              id={id}
              type="password"
              autoComplete="off"
              value={value}
              onChange={(event) => {
                setValue(event.target.value)
              }}
            />
          </div>
          {save.isError && (
            <p role="alert" className="form-error">
              {errorMessage(save.error)}
            </p>
          )}
          <div className="form-actions">
            <Button
              type="submit"
              variant="primary"
              aria-label={`Save ${item.label}`}
              disabled={save.isPending || value === ''}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button
              onClick={() => {
                setEditing(false)
                setValue('')
                save.reset()
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="form-actions">
          <Button
            disabled={!keyOk}
            aria-label={`${item.is_set ? 'Replace' : 'Set'} ${item.label}`}
            onClick={() => {
              setEditing(true)
            }}
          >
            {item.is_set ? 'Replace' : 'Set'}
          </Button>
          {item.is_set && (
            <Button
              variant="danger"
              aria-label={`Remove ${item.label}`}
              onClick={() => {
                setRemoving(true)
              }}
            >
              Remove
            </Button>
          )}
        </div>
      )}
      {removing && (
        <ConfirmDialog
          title={`Remove ${item.label}?`}
          confirmLabel="Remove"
          danger
          busy={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => {
            remove.mutate()
          }}
          onCancel={() => {
            setRemoving(false)
            remove.reset()
          }}
        >
          <p>The stored value is deleted. You will have to type it again to use it.</p>
        </ConfirmDialog>
      )}
    </li>
  )
}

/**
 * The logins kept in the database, encrypted. A value can be typed in, replaced or removed, but it is
 * never shown again: this page only says whether each one is stored and readable.
 */
export function SecretsPanel({ data }: { data: SecretsOut }) {
  const keyOk = data.key === 'ok'
  return (
    <fieldset>
      <legend>Quotex email and password</legend>
      <p className="help">
        Encrypted in the database with the key in <code>backend/.env</code>. A value you type here
        is never shown again. The trading engine uses these when it starts (they win over{' '}
        <code>backend/.env</code>): restart the engine after changing one.
      </p>
      {data.key !== 'ok' && (
        <p role="alert" className="form-error">
          {KEY_PROBLEM[data.key]}
        </p>
      )}
      <ul className="secret-list">
        {data.items
          .filter((item) => item.group === 'logins')
          .map((item) => (
            <SecretRow key={item.name} item={item} keyOk={keyOk} />
          ))}
      </ul>
    </fieldset>
  )
}
