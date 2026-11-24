import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { api } from '../../api/client'
import { keys, useAssetNames, usePrices, useSessions } from '../../api/queries'
import type { Backtest, Pattern, Strategy } from '../../api/types'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'
import { MODES, WEEKDAYS } from '../sessions/sessionSchema'
import { assetLabel } from './assetNames'
import {
  LENGTHS,
  MAX_RUNS,
  MAX_STRATEGIES,
  OPENS,
  PATTERNS,
  PATTERN_TEXT,
  STRATEGIES,
  TREND_MAX_DEFAULT,
  coverage,
  emptyBacktest,
  fromSession,
  parseMultipliers,
  runCount,
  toInput,
  validate,
  type BacktestFormValues,
  type FormErrors,
} from './backtestSchema'

type TextKey = {
  [K in keyof BacktestFormValues]: BacktestFormValues[K] extends string ? K : never
}[keyof BacktestFormValues]

function Field({
  id,
  label,
  error,
  help,
  children,
}: {
  id: string
  label: string
  error?: string
  help?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {help !== undefined && <small className="help">{help}</small>}
      {error !== undefined && (
        <span className="field-error" id={`${id}-error`}>
          {error}
        </span>
      )}
    </div>
  )
}

export function BacktestForm({ onStarted }: { onStarted: (backtest: Backtest) => void }) {
  const client = useQueryClient()
  const prices = usePrices()
  const sessions = useSessions()
  const names = useAssetNames().data?.items ?? []
  const [values, setValues] = useState<BacktestFormValues>(() => emptyBacktest())
  const [errors, setErrors] = useState<FormErrors>({})
  const start = useMutation({
    mutationFn: () => {
      const input = toInput(values)
      // an unnamed run is named after the asset as people know it
      const days =
        values.first_day === values.last_day
          ? values.first_day
          : `${values.first_day} to ${values.last_day}`
      const name = input.name ?? `${assetLabel(input.asset, names)}, ${days}`
      return api.backtests.start({ ...input, name: name.slice(0, 80) })
    },
    onSuccess: (backtest) => {
      void client.invalidateQueries({ queryKey: keys.backtests })
      onStarted(backtest)
    },
  })

  const set = <K extends keyof BacktestFormValues>(key: K, value: BacktestFormValues[K]) => {
    setValues((current) => ({ ...current, [key]: value }))
  }
  const text = (key: TextKey, label: string, help?: ReactNode, type = 'text') => (
    <Field id={`bt-${key}`} label={label} error={errors[key]} help={help}>
      <input
        id={`bt-${key}`}
        type={type}
        value={values[key]}
        aria-invalid={errors[key] !== undefined}
        onChange={(e) => {
          set(key, e.target.value)
        }}
      />
    </Field>
  )

  const held = prices.data?.items ?? []
  const covered = coverage(held, values.asset, values.first_day, values.last_day)
  const covered2 = coverage(held, values.asset, values.check_first_day, values.check_last_day)
  const afterBreakout = values.opens.includes('breakout')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = validate(values)
    setErrors(found)
    if (Object.keys(found).length === 0) start.mutate()
  }

  return (
    <form onSubmit={submit} aria-labelledby="new-backtest-heading" noValidate>
      <h2 id="new-backtest-heading">New backtest</h2>
      <p className="help">
        Replays a trading session on the stored prices: each pair opens a CALL and a PUT on the same
        candle, and every chain follows the live rules of its strategy. Several strategies are
        compared on the same prices.
      </p>
      {(sessions.data?.items.length ?? 0) > 0 && (
        <Field id="bt-copy" label="Copy the setup of a session (optional)">
          <select
            id="bt-copy"
            value=""
            onChange={(e) => {
              const session = sessions.data?.items.find((s) => String(s.id) === e.target.value)
              if (session) setValues((current) => fromSession(current, session))
            }}
          >
            <option value="">Choose a session…</option>
            {sessions.data?.items.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.name} ({s.asset})
              </option>
            ))}
          </select>
        </Field>
      )}
      <fieldset>
        <legend>What to replay</legend>
        {text('name', 'Name (optional)')}
        <Field id="bt-asset" label="Asset" error={errors.asset}>
          <select
            id="bt-asset"
            value={values.asset}
            onChange={(e) => {
              set('asset', e.target.value)
            }}
          >
            {!held.some((h) => h.asset === values.asset) && (
              <option value={values.asset}>
                {assetLabel(values.asset, names)}: no prices stored
              </option>
            )}
            {held.map((h) => (
              <option key={h.asset} value={h.asset}>
                {assetLabel(h.asset, names)}
              </option>
            ))}
          </select>
        </Field>
        {text('first_day', 'First day', undefined, 'date')}
        {text('last_day', 'Last day (included)', undefined, 'date')}
        {covered !== 'all' && (
          <p className="form-warning" role="status">
            {covered === 'none'
              ? `No prices of ${assetLabel(values.asset, names)} are stored for these days: download them above first.`
              : `The prices of ${assetLabel(values.asset, names)} cover only part of these days; candles without prices are skipped and counted.`}
          </p>
        )}
        <fieldset>
          <legend>A second period to judge on (optional)</legend>
          <p className="help">
            Settings that look good on one period can be luck. Choose them on the days above, then
            see whether they still hold on other days: the result shows both, side by side.
          </p>
          {text('check_first_day', 'First day to judge on', undefined, 'date')}
          {text('check_last_day', 'Last day to judge on (included)', undefined, 'date')}
          {covered2 !== 'all' && values.check_first_day !== '' && values.check_last_day !== '' && (
            <p className="form-warning" role="status">
              {covered2 === 'none'
                ? 'No prices are stored for the second period: download them above first.'
                : 'The prices cover only part of the second period.'}
            </p>
          )}
        </fieldset>
      </fieldset>
      <fieldset>
        <legend>The session</legend>
        {text('start_time', 'Window starts', undefined, 'time')}
        {text('end_time', 'Window ends', 'Before the start: the window crosses midnight.', 'time')}
        {text('timezone', 'Time zone', 'UTC, UTC+3 or a name like Africa/Nairobi.')}
        <fieldset>
          <legend>Days of the week</legend>
          <div className="days">
            {WEEKDAYS.map((day) => (
              <label key={day.value} className="check">
                <input
                  type="checkbox"
                  checked={values.weekdays.includes(day.value)}
                  onChange={(e) => {
                    set(
                      'weekdays',
                      e.target.checked
                        ? [...values.weekdays, day.value]
                        : values.weekdays.filter((d) => d !== day.value),
                    )
                  }}
                />
                {day.label}
              </label>
            ))}
          </div>
          {errors.weekdays !== undefined && <span className="field-error">{errors.weekdays}</span>}
        </fieldset>
        <Field id="bt-length" label="Trade length (also the candle)">
          <select
            id="bt-length"
            value={values.duration_s}
            onChange={(e) => {
              set('duration_s', Number(e.target.value))
            }}
          >
            {LENGTHS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id="bt-mode" label="Pairs" help={MODES.find((m) => m.value === values.mode)?.help}>
          <select
            id="bt-mode"
            value={values.mode}
            onChange={(e) => {
              set('mode', e.target.value as BacktestFormValues['mode'])
            }}
          >
            {MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        {values.mode === 'every_candle'
          ? text('max_open_pairs', 'Open pairs at most')
          : text('pause_s', 'Pause between pairs (seconds)')}
        {text('base_stake', 'Base stake')}
        {text('profit_target', 'Profit target per window (optional)')}
        {text('loss_limit', 'Loss limit per window (optional)')}
        {text('max_pairs', 'Most pairs per window (optional)')}
      </fieldset>
      <fieldset>
        <legend>When pairs open</legend>
        <p className="help">
          Choose both to compare them on the same prices. After a breakout, pairs open from the
          candle after it (when it is known, never earlier) until the next consolidation is found or
          the time below runs out; running chains finish, then it waits for the next breakout.
        </p>
        <div className="days">
          {OPENS.map((o) => (
            <label key={o.value} className="check">
              <input
                type="checkbox"
                checked={values.opens.includes(o.value)}
                onChange={(e) => {
                  set(
                    'opens',
                    e.target.checked
                      ? [...values.opens, o.value]
                      : values.opens.filter((v) => v !== o.value),
                  )
                }}
              />
              {o.label}
            </label>
          ))}
        </div>
        {errors.opens !== undefined && <span className="field-error">{errors.opens}</span>}
        {afterBreakout && (
          <>
            <Field
              id="bt-pattern"
              label="A consolidation is"
              help="The same definitions as on the Market page, on candles as long as the trade."
            >
              <select
                id="bt-pattern"
                value={values.pattern}
                onChange={(e) => {
                  set('pattern', e.target.value as Pattern)
                }}
              >
                {PATTERNS.map((p) => (
                  <option key={p} value={p}>
                    {PATTERN_TEXT[p]}
                  </option>
                ))}
              </select>
            </Field>
            {text('pattern_candles', 'Candles in the pattern')}
            {values.pattern === 'mixed' && text('misses', 'Candles that may not alternate')}
            {values.pattern === 'tight' &&
              text('width', 'Range at most (average candles)', 'Like 2: two average candles.')}
            {values.pattern === 'choppy' &&
              text('net_share', 'Net move at most (share)', 'Like 0.2: a fifth of all the moves.')}
            {text('breakout_candles', 'Breakout candles in a row')}
            <Field id="bt-breakout-by" label="Breakout by">
              <select
                id="bt-breakout-by"
                value={values.breakout_by}
                onChange={(e) => {
                  set('breakout_by', e.target.value as BacktestFormValues['breakout_by'])
                }}
              >
                <option value="close">their close beyond the range</option>
                <option value="touch">any part beyond the range</option>
              </select>
            </Field>
            {text(
              'trend_max_candles',
              'Stop after (candles)',
              `Or earlier, at the next consolidation. Empty: only at the next consolidation. ${TREND_MAX_DEFAULT} is how long a trend lasted on Volatility 75 (1s) (the median).`,
            )}
          </>
        )}
      </fieldset>
      <fieldset>
        <legend>Strategies to compare</legend>
        {errors.strategies !== undefined && <p className="field-error">{errors.strategies}</p>}
        {values.strategies.map((row, index) => {
          const steps = parseMultipliers(row.multipliers).length
          const key = `strategies.${String(index)}`
          return (
            <div key={index} className="filters">
              <label>
                Strategy {index + 1}
                <select
                  value={row.strategy}
                  onChange={(e) => {
                    const strategies = [...values.strategies]
                    strategies[index] = { ...row, strategy: e.target.value as Strategy }
                    set('strategies', strategies)
                  }}
                >
                  {STRATEGIES.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Multipliers, one per step ({steps} {steps === 1 ? 'step' : 'steps'})
                <input
                  value={row.multipliers}
                  aria-invalid={errors[key] !== undefined}
                  placeholder="2, 4, 8"
                  onChange={(e) => {
                    const strategies = [...values.strategies]
                    strategies[index] = { ...row, multipliers: e.target.value }
                    set('strategies', strategies)
                  }}
                />
              </label>
              <Button
                variant="quiet"
                onClick={() => {
                  set(
                    'strategies',
                    values.strategies.filter((_, i) => i !== index),
                  )
                }}
              >
                Remove
              </Button>
              {errors[key] !== undefined && <span className="field-error">{errors[key]}</span>}
            </div>
          )
        })}
        {values.strategies.length < MAX_STRATEGIES && (
          <Button
            onClick={() => {
              set('strategies', [
                ...values.strategies,
                { strategy: 'flip_every_loss', multipliers: '2, 4, 8' },
              ])
            }}
          >
            Add a strategy
          </Button>
        )}
      </fieldset>
      <fieldset>
        <legend>Assumptions</legend>
        {text(
          'payout_pct',
          'Payout %',
          'A win pays the stake times this. Deriv keeps no past payouts; 88% is what 1HZ75V paid on the demo.',
        )}
        {text(
          'order_delay_s',
          'Order delay (seconds)',
          'From deciding a trade to its purchase (0.5 s measured).',
        )}
        {text(
          'step_delay_s',
          'Step delay (seconds)',
          'From a trade’s end to deciding the next step (about 1 s with the early result).',
        )}
      </fieldset>
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={start.isPending}>
          Run the backtest
        </Button>
        <small className="help">
          {runCount(values)} of at most {MAX_RUNS} runs (strategies × ways of opening × periods).
        </small>
      </div>
      {start.isError && (
        <p role="alert" className="form-error">
          {errorMessage(start.error)}
        </p>
      )}
    </form>
  )
}
