import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useId, useState, type ReactNode } from 'react'
import { useFieldArray, useForm, useWatch, type FieldError } from 'react-hook-form'
import { Button } from '../../components/Button'
import {
  DEFAULT_MULTIPLIER,
  MAX_STEPS,
  STRATEGIES,
  SUFFIX_MODES,
  groupSchema,
  serverProblems,
  type GroupFormValues,
} from './groupSchema'

export interface PickedChat {
  chat_id: number
  title: string
}

function Field({
  label,
  error,
  help,
  children,
}: {
  label: string
  error?: FieldError | undefined
  help?: string
  children: (props: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode
}) {
  const id = useId()
  const helpId = `${id}-help`
  const errorId = `${id}-error`
  const describedBy = [help ? helpId : null, error ? errorId : null].filter(Boolean).join(' ')
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({ id, describedBy: describedBy || undefined, invalid: error !== undefined })}
      {help && (
        <small id={helpId} className="help">
          {help}
        </small>
      )}
      {error && (
        <small id={errorId} className="field-error" role="alert">
          {error.message}
        </small>
      )}
    </div>
  )
}

/**
 * Create or edit a group. There is exactly one multiplier input per step: changing "Steps" adds or
 * removes inputs, and every one must be a number above 0. `onSubmit` may throw the API's error: its
 * field problems are shown on the matching inputs.
 */
export function GroupForm({
  initial,
  mode,
  onSubmit,
  onCancel,
  chatPicker,
}: {
  initial: GroupFormValues
  mode: 'create' | 'edit'
  onSubmit: (values: GroupFormValues) => Promise<void>
  onCancel: () => void
  /** Shown when adding a group: a way to pick the Telegram chat from a list. */
  chatPicker?: (pick: (chat: PickedChat) => void) => ReactNode
}) {
  const form = useForm<GroupFormValues>({
    resolver: zodResolver(groupSchema),
    defaultValues: initial,
    mode: 'onBlur',
  })
  const { register, control, handleSubmit, setValue, setError, formState } = form
  const { fields, replace } = useFieldArray({ control, name: 'multipliers' })
  const [formError, setFormError] = useState<string | null>(null)

  const strategy = useWatch({ control, name: 'strategy' })
  const steps = useWatch({ control, name: 'max_steps' })
  const noFollowUps = strategy === 'no_martingale'

  // "No martingale" has no follow-ups: it always has 0 steps.
  useEffect(() => {
    if (noFollowUps) setValue('max_steps', 0)
  }, [noFollowUps, setValue])

  // One multiplier input per step: grow or shrink the list as the number of steps changes.
  useEffect(() => {
    if (!Number.isInteger(steps) || steps < 0 || steps > MAX_STEPS) return
    const current = form.getValues('multipliers')
    if (current.length === steps) return
    replace(
      steps > current.length
        ? [
            ...current,
            ...Array.from({ length: steps - current.length }, () => ({
              value: DEFAULT_MULTIPLIER,
            })),
          ]
        : current.slice(0, steps),
    )
  }, [steps, form, replace])

  // Picking a chat fills in its id; the name only if the owner has not typed one already.
  const pickChat = (chat: PickedChat) => {
    setValue('telegram_chat_id', String(chat.chat_id), { shouldValidate: true, shouldDirty: true })
    if (form.getValues('title').trim() === '') {
      setValue('title', chat.title, { shouldValidate: true, shouldDirty: true })
    }
  }

  const submit = handleSubmit(async (values) => {
    setFormError(null)
    try {
      await onSubmit(values)
    } catch (error) {
      const { fields: problems, message } = serverProblems(error)
      let general = message
      for (const problem of problems) {
        if (problem.name === 'root') general = problem.message
        else setError(problem.name, { type: 'server', message: problem.message })
      }
      setFormError(general)
    }
  })

  const errors = formState.errors
  const multiplierErrors = errors.multipliers
  const help = STRATEGIES.find((s) => s.value === strategy)?.help

  return (
    <form onSubmit={(event) => void submit(event)} noValidate aria-label="Group settings">
      {formError !== null && (
        <p role="alert" className="form-error">
          {formError}
        </p>
      )}

      <fieldset>
        <legend>Group</legend>
        {mode === 'create' && chatPicker?.(pickChat)}
        <Field label="Name" error={errors.title}>
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('title')}
            />
          )}
        </Field>
        <Field
          label="Telegram chat id"
          error={errors.telegram_chat_id}
          help={
            mode === 'create' && chatPicker !== undefined
              ? 'Use "Choose from my Telegram chats" above to fill this in. It cannot be changed later: that would be a different group.'
              : 'Find it by running npm run telegram:dialogs. It cannot be changed later: that would be a different group.'
          }
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              inputMode="numeric"
              readOnly={mode === 'edit'}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('telegram_chat_id')}
            />
          )}
        </Field>
        <label className="check">
          <input type="checkbox" {...register('enabled')} />
          Enabled (listen to this group)
        </label>
      </fieldset>

      <fieldset>
        <legend>Strategy</legend>
        <Field label="Strategy" error={errors.strategy} {...(help ? { help } : {})}>
          {({ id, describedBy }) => (
            <select id={id} aria-describedby={describedBy} {...register('strategy')}>
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Base stake" error={errors.base_stake} help="The first trade of every chain.">
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              inputMode="decimal"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('base_stake')}
            />
          )}
        </Field>
        <Field
          label="Steps"
          error={errors.max_steps}
          help="How many follow-up trades after a loss. One multiplier input appears for each."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              type="number"
              min={0}
              max={MAX_STEPS}
              disabled={noFollowUps}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('max_steps', { valueAsNumber: true })}
            />
          )}
        </Field>
        {!noFollowUps && fields.length > 0 && (
          <div className="multipliers" role="group" aria-label="Multipliers, one per step">
            {fields.map((field, index) => (
              <Field
                key={field.id}
                label={`Multiplier for step ${String(index + 1)}`}
                error={multiplierErrors?.[index]?.value}
              >
                {({ id, describedBy, invalid }) => (
                  <input
                    id={id}
                    inputMode="decimal"
                    aria-describedby={describedBy}
                    aria-invalid={invalid}
                    {...register(`multipliers.${String(index) as `${number}`}.value`)}
                  />
                )}
              </Field>
            ))}
          </div>
        )}
        <Field
          label="Minimum payout (%)"
          error={errors.min_payout_pct}
          help="A signal on an asset paying less than this is not traded. 0 turns the check off."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              type="number"
              min={0}
              max={100}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('min_payout_pct', { valueAsNumber: true })}
            />
          )}
        </Field>
      </fieldset>

      <fieldset>
        <legend>Reading the signals</legend>
        <Field label="Parser" error={errors.parser}>
          {({ id, describedBy }) => (
            <select id={id} aria-describedby={describedBy} {...register('parser')}>
              <option value="legacy_v1">legacy_v1 (the old bot’s formats)</option>
            </select>
          )}
        </Field>
        <Field label="OTC assets" error={errors.asset_suffix_mode}>
          {({ id, describedBy }) => (
            <select id={id} aria-describedby={describedBy} {...register('asset_suffix_mode')}>
              {SUFFIX_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          label="Time zone of the group"
          error={errors.timezone}
          help="Entry times in messages are read in this zone: UTC-3, UTC+5:30 or a name like Africa/Nairobi."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('timezone')}
            />
          )}
        </Field>
      </fieldset>

      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={formState.isSubmitting}>
          {formState.isSubmitting ? 'Saving…' : mode === 'create' ? 'Create group' : 'Save changes'}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  )
}
