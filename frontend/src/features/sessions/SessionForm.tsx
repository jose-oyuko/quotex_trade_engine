import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useFieldArray, useForm, useWatch } from 'react-hook-form'
import { Button } from '../../components/Button'
import { formatMoney } from '../../lib/format'
import { Field } from '../groups/GroupForm'
import {
  DEFAULT_MULTIPLIER,
  MAX_STEPS,
  MODES,
  REPEATS,
  STRATEGIES,
  TRADE_LENGTHS,
  WEEKDAYS,
  boundaryWarning,
  serverProblems,
  sessionSchema,
  worstCase,
  type SessionFormValues,
} from './sessionSchema'

/**
 * Create or edit a trading session. There is exactly one multiplier input per step. Below the
 * stakes the form says in figures what the most is that can be at stake, and warns when the start
 * is not on a candle boundary. `onSubmit` may throw the API's error: its field problems (an
 * overlapping window, say) are shown on the matching inputs.
 */
export function SessionForm({
  initial,
  mode,
  onSubmit,
  onCancel,
}: {
  initial: SessionFormValues
  mode: 'create' | 'edit'
  onSubmit: (values: SessionFormValues) => Promise<void>
  onCancel: () => void
}) {
  const form = useForm<SessionFormValues>({
    resolver: zodResolver(sessionSchema),
    defaultValues: initial,
    mode: 'onBlur',
  })
  const { register, control, handleSubmit, setValue, setError, formState } = form
  const { fields, replace } = useFieldArray({ control, name: 'multipliers' })
  const [formError, setFormError] = useState<string | null>(null)

  const values = useWatch({ control }) as SessionFormValues
  const strategy = values.strategy
  const steps = values.max_steps
  const noFollowUps = strategy === 'no_martingale'
  const everyCandle = values.mode === 'every_candle'

  useEffect(() => {
    if (noFollowUps) setValue('max_steps', 0)
  }, [noFollowUps, setValue])

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

  const submit = handleSubmit(async (checked) => {
    setFormError(null)
    try {
      await onSubmit(checked)
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
  const modeHelp = MODES.find((m) => m.value === values.mode)?.help
  const startWarning = boundaryWarning(values)
  const worst = worstCase(values)
  const days = values.weekdays

  return (
    <form onSubmit={(event) => void submit(event)} noValidate aria-label="Session settings">
      {formError !== null && (
        <p role="alert" className="form-error">
          {formError}
        </p>
      )}

      <fieldset>
        <legend>Session</legend>
        <Field label="Name" error={errors.name}>
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('name')}
            />
          )}
        </Field>
        <label className="check">
          <input type="checkbox" {...register('enabled')} />
          Enabled (it starts by itself at its start time)
        </label>
      </fieldset>

      <fieldset>
        <legend>What to trade</legend>
        <Field
          label="Asset"
          error={errors.asset}
          help="The Quotex name: EURUSD, or EURUSD_otc for the over-the-counter market (the only one open at the weekend)."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('asset')}
            />
          )}
        </Field>
        <Field
          label="Trade length"
          error={errors.duration_s}
          help="Every trade lasts this long, and so does a candle."
        >
          {({ id, describedBy }) => (
            <select
              id={id}
              aria-describedby={describedBy}
              {...register('duration_s', { valueAsNumber: true })}
            >
              {TRADE_LENGTHS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          )}
        </Field>
      </fieldset>

      <fieldset>
        <legend>When</legend>
        <Field label="Starts at" error={errors.start_time}>
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              type="time"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('start_time')}
            />
          )}
        </Field>
        <Field
          label="Ends at"
          error={errors.end_time}
          help="An end before the start means the window crosses midnight."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              type="time"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('end_time')}
            />
          )}
        </Field>
        <Field
          label="Time zone"
          error={errors.timezone}
          help="The zone the two times above are in: UTC-3, UTC+5:30 or a name like Africa/Nairobi."
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
        {startWarning !== null && (
          <p role="note" className="form-warning">
            {startWarning}
          </p>
        )}
        <Field label="How often" error={errors.repeat}>
          {({ id, describedBy }) => (
            <select id={id} aria-describedby={describedBy} {...register('repeat')}>
              {REPEATS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        {values.repeat === 'chosen' && (
          <div className="field" role="group" aria-label="Days of the week">
            <div className="days">
              {WEEKDAYS.map((day) => (
                <label key={day.value} className="check">
                  <input
                    type="checkbox"
                    checked={days.includes(day.value)}
                    onChange={(event) => {
                      setValue(
                        'weekdays',
                        event.target.checked
                          ? [...days, day.value]
                          : days.filter((d) => d !== day.value),
                        { shouldValidate: true, shouldDirty: true },
                      )
                    }}
                  />
                  {day.label}
                </label>
              ))}
            </div>
            {errors.weekdays?.message !== undefined && (
              <small className="field-error" role="alert">
                {errors.weekdays.message}
              </small>
            )}
          </div>
        )}
      </fieldset>

      <fieldset>
        <legend>How pairs are opened</legend>
        <Field label="Pairs" error={errors.mode} {...(modeHelp ? { help: modeHelp } : {})}>
          {({ id, describedBy }) => (
            <select id={id} aria-describedby={describedBy} {...register('mode')}>
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        {everyCandle ? (
          <Field
            label="Open pairs at most"
            error={errors.max_open_pairs}
            help="A pair is open while one of its two trades is running. More open pairs means more at stake at once."
          >
            {({ id, describedBy, invalid }) => (
              <input
                id={id}
                type="number"
                min={1}
                max={50}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                {...register('max_open_pairs', { valueAsNumber: true })}
              />
            )}
          </Field>
        ) : (
          <Field
            label="Pause after a pair (seconds)"
            error={errors.pause_s}
            help="Waited once both trades of a pair have ended; the next pair then opens on the next candle."
          >
            {({ id, describedBy, invalid }) => (
              <input
                id={id}
                type="number"
                min={0}
                max={86400}
                aria-describedby={describedBy}
                aria-invalid={invalid}
                {...register('pause_s', { valueAsNumber: true })}
              />
            )}
          </Field>
        )}
        <Field
          label="Stop after this many pairs"
          error={errors.max_pairs}
          help="Optional. Leave empty for no limit."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              inputMode="numeric"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('max_pairs')}
            />
          )}
        </Field>
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
        <p className="help">
          Each pair is a CALL and a PUT at once. The one that wins ends; the one that loses follows
          this strategy until it wins or runs out of steps.
        </p>
        <Field label="Base stake" error={errors.base_stake} help="The first trade of each leg.">
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
          help="A round where the asset pays less than this is skipped, and nothing is sent. 0 turns the check off."
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
        <legend>When to stop</legend>
        <Field
          label="Profit target"
          error={errors.profit_target}
          help="Optional. The session stops opening pairs when its profit reaches this."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              inputMode="decimal"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('profit_target')}
            />
          )}
        </Field>
        <Field
          label="Loss limit"
          error={errors.loss_limit}
          help="Optional. The session stops opening pairs when its loss reaches this."
        >
          {({ id, describedBy, invalid }) => (
            <input
              id={id}
              inputMode="decimal"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              {...register('loss_limit')}
            />
          )}
        </Field>
        <p className="help">
          Stopping never cuts a trade off: no new pair opens, but a chain that is recovering keeps
          going until it wins or runs out of steps. So the loss limit is <strong>not</strong> a cap
          on the loss.
        </p>
        {worst !== null && (
          <div className="worst-case" role="note" aria-label="The most that can be at stake">
            <p>
              <strong>The most that can be at stake.</strong> One pair can have staked up to{' '}
              <strong>{formatMoney(worst.perPair.toFixed(2))}</strong> (both first trades, then
              every step of the leg that keeps losing).
              {worst.pairsAtOnce > 1 && (
                <>
                  {' '}
                  With {worst.pairsAtOnce} pairs open at once, up to{' '}
                  <strong>{formatMoney(worst.together.toFixed(2))}</strong> together.
                </>
              )}{' '}
              This counts stakes only, not what the wins pay back. Make sure your maximum stake
              limits allow the last steps, or the chain ends early.
            </p>
          </div>
        )}
      </fieldset>

      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={formState.isSubmitting}>
          {formState.isSubmitting
            ? 'Saving…'
            : mode === 'create'
              ? 'Create session'
              : 'Save changes'}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  )
}
