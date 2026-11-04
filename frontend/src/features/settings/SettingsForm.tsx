import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { SettingItem, SettingsOut } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'

const SOURCE_TEXT: Record<SettingItem['source'], string> = {
  database: 'set here',
  environment: 'from backend/.env',
  default: 'built-in default',
}

function SettingField({
  item,
  value,
  onChange,
  onReset,
  busy,
}: {
  item: SettingItem
  value: string
  onChange: (value: string) => void
  onReset: () => void
  busy: boolean
}) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{item.label}</label>
      {item.kind === 'choice' ? (
        <select
          id={id}
          value={value}
          onChange={(event) => {
            onChange(event.target.value)
          }}
        >
          {item.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          type="text"
          value={value}
          autoComplete="off"
          onChange={(event) => {
            onChange(event.target.value)
          }}
        />
      )}
      <small className="help">{item.help}</small>
      <small className="help">
        <Badge tone={item.source === 'database' ? 'info' : 'muted'}>
          {SOURCE_TEXT[item.source]}
        </Badge>{' '}
        {item.source === 'database' && (
          <Button variant="quiet" onClick={onReset} disabled={busy}>
            Go back to {item.default_value}
          </Button>
        )}
      </small>
    </div>
  )
}

/** The few settings that used to be lines in `backend/.env`. Saved ones apply at the next start. */
export function SettingsForm({ data }: { data: SettingsOut }) {
  const client = useQueryClient()
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(data.items.map((item) => [item.key, item.value])),
  )
  const save = useMutation({
    mutationFn: (values: Record<string, string | null>) => api.settings.save(values),
    onSuccess: (saved) => {
      client.setQueryData(keys.settings, saved)
      setDraft(Object.fromEntries(saved.items.map((item) => [item.key, item.value])))
    },
  })

  const changed = Object.fromEntries(
    data.items.filter((item) => draft[item.key] !== item.value).map((i) => [i.key, draft[i.key]]),
  ) as Record<string, string>
  const dirty = Object.keys(changed).length > 0

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (dirty) save.mutate(changed)
      }}
    >
      <fieldset>
        <legend>Application settings</legend>
        {data.items.map((item) => (
          <SettingField
            key={item.key}
            item={item}
            value={draft[item.key] ?? item.value}
            busy={save.isPending}
            onChange={(value) => {
              setDraft((current) => ({ ...current, [item.key]: value }))
            }}
            onReset={() => {
              save.mutate({ [item.key]: null })
            }}
          />
        ))}
        {save.isError && (
          <p role="alert" className="form-error">
            {errorMessage(save.error)}
          </p>
        )}
        {save.isSuccess && !dirty && <p role="status">Saved. {data.apply_note}</p>}
        <div className="form-actions">
          <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
        <p className="help">{data.apply_note}</p>
      </fieldset>
    </form>
  )
}
