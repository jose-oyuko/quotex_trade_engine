// The definition to scan with (decision D-85): the period, the pattern and its settings, and what
// counts as a breakout. Checked here as typed; the server checks again.
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import type { MarketRules, Pattern } from '../../api/types'
import { Button } from '../../components/Button'
import {
  PATTERNS,
  PATTERN_TEXT,
  rulesToForm,
  validateScan,
  type ScanErrors,
  type ScanFormValues,
} from './marketSchema'

function Field({
  label,
  error,
  help,
  children,
}: {
  label: string
  error: string | undefined
  help?: string
  children: (id: string, describedBy: string | undefined) => ReactNode
}) {
  const id = useId()
  const describedBy = [help ? `${id}-help` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(' ')
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id, describedBy || undefined)}
      {help && (
        <small id={`${id}-help`} className="help">
          {help}
        </small>
      )}
      {error && (
        <small id={`${id}-error`} className="field-error" role="alert">
          {error}
        </small>
      )}
    </div>
  )
}

export function ScanForm({
  values,
  onChange,
  defaults,
  busy,
  onScan,
}: {
  values: ScanFormValues
  onChange: (values: ScanFormValues) => void
  /** Each pattern's own defaults, from the server. */
  defaults: readonly MarketRules[]
  busy: boolean
  onScan: () => void
}) {
  const [errors, setErrors] = useState<ScanErrors>({})
  const set = (key: keyof ScanFormValues, value: string) => {
    onChange({ ...values, [key]: value })
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = validateScan(values)
    setErrors(found)
    if (Object.keys(found).length === 0) onScan()
  }
  const number = (key: keyof ScanFormValues, label: string, help?: string) => (
    <Field label={label} error={errors[key]} help={help}>
      {(id, describedBy) => (
        <input
          id={id}
          inputMode="decimal"
          value={values[key]}
          aria-invalid={errors[key] !== undefined}
          aria-describedby={describedBy}
          onChange={(e) => {
            set(key, e.target.value)
          }}
        />
      )}
    </Field>
  )

  return (
    <form onSubmit={submit} aria-labelledby="scan-heading" noValidate>
      <h2 id="scan-heading">Find consolidations</h2>
      <p className="help">
        The last stored day is scanned with your definition when the page opens. Change the period
        or what counts as a consolidation and <em>Scan</em> again: each one is outlined on the chart
        and listed. Times are UTC.
      </p>
      <div className="filters">
        <Field label="From (UTC)" error={errors.start}>
          {(id, describedBy) => (
            <input
              id={id}
              type="datetime-local"
              value={values.start}
              aria-describedby={describedBy}
              onChange={(e) => {
                set('start', e.target.value)
              }}
            />
          )}
        </Field>
        <Field label="To (UTC)" error={errors.end} help="At most 31 days.">
          {(id, describedBy) => (
            <input
              id={id}
              type="datetime-local"
              value={values.end}
              aria-describedby={describedBy}
              onChange={(e) => {
                set('end', e.target.value)
              }}
            />
          )}
        </Field>
      </div>
      <div className="filters">
        <Field label="Pattern" error={undefined}>
          {(id) => (
            <select
              id={id}
              value={values.pattern}
              onChange={(e) => {
                const pattern = e.target.value as Pattern
                const own = defaults.find((d) => d.pattern === pattern)
                // a new pattern starts from its own settings; the breakout stays as chosen
                onChange({
                  ...values,
                  ...(own ? rulesToForm(own) : { pattern }),
                  breakout_candles: values.breakout_candles,
                  breakout_by: values.breakout_by,
                })
              }}
            >
              {PATTERNS.map((p) => (
                <option key={p} value={p}>
                  {PATTERN_TEXT[p]}
                </option>
              ))}
            </select>
          )}
        </Field>
        {number('candles', 'Candles in the pattern')}
        {values.pattern === 'mixed' &&
          number('misses', 'Candles that may not alternate', 'In the pattern’s candles.')}
        {values.pattern === 'tight' &&
          number('width', 'Range at most (average candles)', 'Like 2: two average candles.')}
        {values.pattern === 'choppy' &&
          number('net_share', 'Net move at most (share)', 'Like 0.2: a fifth of all the moves.')}
      </div>
      <div className="filters">
        {number('breakout_candles', 'Breakout candles in a row')}
        <Field label="Breakout by" error={undefined}>
          {(id) => (
            <select
              id={id}
              value={values.breakout_by}
              onChange={(e) => {
                set('breakout_by', e.target.value)
              }}
            >
              <option value="close">their close beyond the range</option>
              <option value="touch">any part beyond the range</option>
            </select>
          )}
        </Field>
      </div>
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Scanning…' : 'Scan'}
        </Button>
      </div>
    </form>
  )
}
