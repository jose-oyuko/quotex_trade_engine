// What the backtest form accepts. It mirrors backend/app/api/schemas/backtests.py so a mistake is
// caught while typing; the server checks everything again.
import type { BacktestInput, PriceAsset, Session, Strategy } from '../../api/types'
import { GROWING_FLIP_MAX_STEPS, MAX_STEPS, STRATEGIES } from '../groups/groupSchema'

export { STRATEGIES }

export const MAX_STRATEGIES = 6
export const MAX_DAYS = 92

/** Deriv's trade lengths a backtest offers (a candle is as long as the trade). */
export const LENGTHS = [
  { value: 60, label: '1 minute' },
  { value: 120, label: '2 minutes' },
  { value: 180, label: '3 minutes' },
  { value: 300, label: '5 minutes' },
  { value: 600, label: '10 minutes' },
  { value: 900, label: '15 minutes' },
  { value: 1800, label: '30 minutes' },
  { value: 3600, label: '1 hour' },
] as const

export interface StrategyRow {
  strategy: Strategy
  /** One multiplier per step, separated by commas: "2, 4, 8". Empty: no steps. */
  multipliers: string
}

export interface BacktestFormValues {
  name: string
  asset: string
  first_day: string
  last_day: string
  start_time: string
  end_time: string
  timezone: string
  weekdays: number[]
  duration_s: number
  mode: 'sequential' | 'every_candle'
  max_open_pairs: string
  pause_s: string
  max_pairs: string
  profit_target: string
  loss_limit: string
  base_stake: string
  payout_pct: string
  order_delay_s: string
  step_delay_s: string
  strategies: StrategyRow[]
}

export type FormErrors = Partial<Record<string, string>>

const pad = (n: number) => String(n).padStart(2, '0')
export const isoDay = (d: Date) =>
  `${String(d.getUTCFullYear())}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`

export function emptyBacktest(today: Date = new Date()): BacktestFormValues {
  const yesterday = new Date(today.getTime() - 86_400_000)
  return {
    name: '',
    asset: '1HZ75V',
    first_day: isoDay(yesterday),
    last_day: isoDay(yesterday),
    start_time: '10:00',
    end_time: '14:00',
    timezone: 'UTC',
    weekdays: [0, 1, 2, 3, 4, 5, 6],
    duration_s: 60,
    mode: 'sequential',
    max_open_pairs: '1',
    pause_s: '0',
    max_pairs: '',
    profit_target: '',
    loss_limit: '',
    base_stake: '1.00',
    payout_pct: '88',
    order_delay_s: '0.5',
    step_delay_s: '1.0',
    strategies: [
      { strategy: 'martingale', multipliers: '2, 4, 8' },
      { strategy: 'growing_flip', multipliers: '2, 4, 8, 16, 32, 64, 128, 256' },
    ],
  }
}

export function parseMultipliers(text: string): string[] {
  return text
    .split(/[,\s]+/)
    .map((part) => part.trim())
    .filter((part) => part !== '')
}

const MONEY = /^\d+(\.\d{1,2})?$/
const MULTIPLIER = /^\d+(\.\d{1,4})?$/
const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/
const WHOLE = /^\d+$/
const DECIMAL = /^\d+(\.\d+)?$/

function days(first: string, last: string): number {
  return (
    Math.round((Date.parse(`${last}T00:00:00Z`) - Date.parse(`${first}T00:00:00Z`)) / 86_400_000) +
    1
  )
}

export function strategyProblem(row: StrategyRow): string | null {
  const parts = parseMultipliers(row.multipliers)
  if (parts.some((p) => !MULTIPLIER.test(p) || Number(p) <= 0 || Number(p) > 1000)) {
    return 'Multipliers are numbers like 2 or 2.5, separated by commas'
  }
  if (row.strategy === 'no_martingale' && parts.length > 0) {
    return 'No martingale has no steps: leave the multipliers empty'
  }
  if (parts.length > MAX_STEPS) return `At most ${String(MAX_STEPS)} steps`
  if (row.strategy === 'growing_flip' && parts.length > GROWING_FLIP_MAX_STEPS) {
    return `Growing flip has at most ${String(GROWING_FLIP_MAX_STEPS)} steps (9 trades in all)`
  }
  return null
}

export function validate(values: BacktestFormValues): FormErrors {
  const errors: FormErrors = {}
  if (!/^\w{2,30}$/.test(values.asset.trim())) errors.asset = 'Choose an asset, like 1HZ75V'
  if (!values.first_day) errors.first_day = 'Choose the first day'
  if (!values.last_day) errors.last_day = 'Choose the last day'
  if (values.first_day && values.last_day) {
    const n = days(values.first_day, values.last_day)
    if (n < 1) errors.last_day = 'The last day must not be before the first'
    else if (n > MAX_DAYS) errors.last_day = `At most ${String(MAX_DAYS)} days per backtest`
  }
  if (!CLOCK.test(values.start_time)) errors.start_time = 'Use a time like 10:00'
  if (!CLOCK.test(values.end_time)) errors.end_time = 'Use a time like 14:00'
  else if (values.start_time === values.end_time) {
    errors.end_time = 'The window needs a start and an end that are different'
  }
  if (!values.timezone.trim()) errors.timezone = 'Enter a time zone, like UTC or UTC+3'
  if (values.weekdays.length === 0) errors.weekdays = 'Choose at least one day of the week'
  if (!MONEY.test(values.base_stake) || Number(values.base_stake) <= 0) {
    errors.base_stake = 'Use an amount like 1.00'
  }
  for (const key of ['profit_target', 'loss_limit'] as const) {
    if (values[key] !== '' && (!MONEY.test(values[key]) || Number(values[key]) <= 0)) {
      errors[key] = 'An amount like 10.00, or empty for none'
    }
  }
  if (values.max_pairs !== '' && (!WHOLE.test(values.max_pairs) || Number(values.max_pairs) < 1)) {
    errors.max_pairs = 'A whole number, or empty for no limit'
  }
  const open = Number(values.max_open_pairs)
  if (!WHOLE.test(values.max_open_pairs) || open < 1 || open > 50) {
    errors.max_open_pairs = 'A whole number from 1 to 50'
  }
  if (!WHOLE.test(values.pause_s) || Number(values.pause_s) > 86_400) {
    errors.pause_s = 'A whole number of seconds'
  }
  const payout = Number(values.payout_pct)
  if (!DECIMAL.test(values.payout_pct) || payout <= 0 || payout > 100) {
    errors.payout_pct = 'A percentage above 0 and at most 100'
  }
  if (!DECIMAL.test(values.order_delay_s) || Number(values.order_delay_s) > 10) {
    errors.order_delay_s = 'Seconds, from 0 to 10'
  }
  if (!DECIMAL.test(values.step_delay_s) || Number(values.step_delay_s) > 60) {
    errors.step_delay_s = 'Seconds, from 0 to 60'
  }
  if (values.strategies.length === 0) errors.strategies = 'Add at least one strategy'
  if (values.strategies.length > MAX_STRATEGIES) {
    errors.strategies = `At most ${String(MAX_STRATEGIES)} strategies at once`
  }
  values.strategies.forEach((row, index) => {
    const problem = strategyProblem(row)
    if (problem !== null) errors[`strategies.${String(index)}`] = problem
  })
  return errors
}

const orNull = (text: string) => (text.trim() === '' ? null : text.trim())

export function toInput(values: BacktestFormValues): BacktestInput {
  return {
    name: orNull(values.name),
    asset: values.asset.trim(),
    first_day: values.first_day,
    last_day: values.last_day,
    start_time: values.start_time,
    end_time: values.end_time,
    timezone: values.timezone.trim(),
    weekdays: [...values.weekdays].sort(),
    duration_s: values.duration_s,
    mode: values.mode,
    pause_s: Number(values.pause_s),
    max_open_pairs: Number(values.max_open_pairs),
    max_pairs: values.max_pairs === '' ? null : Number(values.max_pairs),
    profit_target: orNull(values.profit_target),
    loss_limit: orNull(values.loss_limit),
    base_stake: values.base_stake,
    payout_pct: values.payout_pct,
    order_delay_s: Number(values.order_delay_s),
    step_delay_s: Number(values.step_delay_s),
    strategies: values.strategies.map((row) => {
      const multipliers = parseMultipliers(row.multipliers)
      return { strategy: row.strategy, max_steps: multipliers.length, multipliers }
    }),
  }
}

/** The form filled from a saved session: its window, mode, limits and strategy. */
export function fromSession(values: BacktestFormValues, session: Session): BacktestFormValues {
  const s = session.strategy
  return {
    ...values,
    name: `${session.name} (backtest)`,
    asset: session.asset,
    start_time: session.start_time.slice(0, 5),
    end_time: session.end_time.slice(0, 5),
    timezone: session.timezone,
    weekdays: session.weekdays.length > 0 ? [...session.weekdays] : values.weekdays,
    duration_s: session.duration_s,
    mode: session.mode,
    max_open_pairs: String(session.max_open_pairs),
    pause_s: String(session.pause_s),
    max_pairs: session.max_pairs === null ? '' : String(session.max_pairs),
    profit_target: session.profit_target ?? '',
    loss_limit: session.loss_limit ?? '',
    base_stake: s === null ? values.base_stake : s.base_stake,
    strategies:
      s === null
        ? values.strategies
        : [{ strategy: s.strategy, multipliers: s.multipliers.join(', ') }],
  }
}

/** Whether the stored prices of `asset` cover the chosen days (from 00:00 UTC of the first to
 * 24:00 UTC of the last): "all", "part" or "none". The server decides exactly; this warns. */
export function coverage(
  held: PriceAsset[],
  asset: string,
  first: string,
  last: string,
): 'all' | 'part' | 'none' {
  const found = held.find((h) => h.asset === asset.trim())
  if (!found || !first || !last) return 'none'
  const from = Date.parse(`${first}T00:00:00Z`)
  const to = Date.parse(`${last}T23:59:59Z`)
  let cursor = from
  let any = false
  for (const range of found.ranges) {
    const a = Date.parse(range.start)
    const b = Date.parse(range.end)
    if (b < from || a > to) continue
    any = true
    if (a <= cursor + 1000) cursor = Math.max(cursor, b)
  }
  if (cursor >= to - 1000) return 'all'
  return any ? 'part' : 'none'
}
