// What the session form accepts. It mirrors the backend's rules (backend/app/api/schemas/sessions.py
// and app/services/sessions.py) so a mistake is caught while typing; the server checks everything
// again, and its answer is shown on the same fields if it disagrees.
import { z } from 'zod'
import { ApiError } from '../../api/client'
import type { Session, SessionInput } from '../../api/types'
import { MAX_STEPS, STRATEGIES, DEFAULT_MULTIPLIER } from '../groups/groupSchema'

export { MAX_STEPS, STRATEGIES, DEFAULT_MULTIPLIER }

/** The trade lengths Quotex offers in whole minutes; a candle is as long as the trade. */
export const TRADE_LENGTHS = [
  { value: 60, label: '1 minute (M1)' },
  { value: 120, label: '2 minutes (M2)' },
  { value: 180, label: '3 minutes (M3)' },
  { value: 300, label: '5 minutes (M5)' },
  { value: 600, label: '10 minutes (M10)' },
  { value: 900, label: '15 minutes (M15)' },
  { value: 1800, label: '30 minutes (M30)' },
  { value: 3600, label: '1 hour (H1)' },
  { value: 14400, label: '4 hours (H4)' },
] as const

export const WEEKDAYS = [
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
  { value: 6, label: 'Sun' },
] as const

export const REPEATS = [
  { value: 'once', label: 'Once: only the next window, never again' },
  { value: 'every_day', label: 'Every day' },
  { value: 'mon_fri', label: 'Monday to Friday' },
  { value: 'chosen', label: 'On the days I choose' },
] as const

export const MODES = [
  {
    value: 'sequential',
    label: 'One pair at a time',
    help: 'When both trades of a pair have ended, it waits the pause below, then opens the next pair on the next candle.',
  },
  {
    value: 'every_candle',
    label: 'A pair at every candle',
    help: 'A new pair at every candle while earlier pairs keep running, up to the number of open pairs below. A candle that finds the limit reached is skipped.',
  },
] as const

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
const WORK_DAYS = [0, 1, 2, 3, 4]

const money = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, 'Use a number with at most 2 decimals, like 10.00')
  .refine((value) => Number(value) > 0, 'Must be greater than 0')
  .refine((value) => Number(value) <= 1_000_000, 'That is too large')

/** Blank means "none". */
const optionalMoney = z.union([z.literal(''), money])

const stake = money
const multiplier = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,4})?$/, 'Use a number like 2 or 2.5')
  .refine((value) => Number(value) > 0, 'Must be greater than 0')
  .refine((value) => Number(value) <= 1000, 'That is too large')

const clock = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, 'Use a time like 11:00')

const whole = (message: string, min: number, max: number) =>
  z.number({ error: message }).int(message).min(min, message).max(max, message)

export const sessionSchema = z
  .object({
    name: z.string().trim().min(1, 'Give the session a name').max(80, 'At most 80 characters'),
    enabled: z.boolean(),
    asset: z
      .string()
      .trim()
      .regex(
        /^[A-Za-z0-9]{3,12}(_otc)?$/,
        'Use the Quotex name: letters and digits, like EURUSD or EURUSD_otc',
      ),
    duration_s: z
      .number({ error: 'Choose a trade length' })
      .refine((value) => TRADE_LENGTHS.some((t) => t.value === value), 'Choose a trade length'),
    start_time: clock,
    end_time: clock,
    timezone: z.string().trim().min(1, 'Enter a time zone, like UTC-3 or Africa/Nairobi').max(64),
    repeat: z.enum(['once', 'every_day', 'mon_fri', 'chosen']),
    weekdays: z.array(z.number().int().min(0).max(6)),
    mode: z.enum(['sequential', 'every_candle']),
    max_open_pairs: whole('Enter a whole number from 1 to 50', 1, 50),
    pause_s: whole('Enter a whole number of seconds, 0 to 86400', 0, 86_400),
    profit_target: optionalMoney,
    loss_limit: optionalMoney,
    max_pairs: z.union([
      z.literal(''),
      z
        .string()
        .trim()
        .regex(/^[1-9]\d{0,4}$/, 'Enter a whole number, or leave it empty for no limit'),
    ]),
    strategy: z.enum(['no_martingale', 'martingale', 'flip_every_loss', 'two_step_flip']),
    base_stake: stake,
    max_steps: whole(`Enter a whole number from 0 to ${String(MAX_STEPS)}`, 0, MAX_STEPS),
    multipliers: z.array(z.object({ value: multiplier })),
    min_payout_pct: whole('Enter a whole number from 0 to 100', 0, 100),
  })
  .superRefine((values, context) => {
    if (values.start_time === values.end_time) {
      context.addIssue({
        code: 'custom',
        path: ['end_time'],
        message: 'The window needs a start and an end that are different',
      })
    }
    if (values.repeat === 'chosen' && values.weekdays.length === 0) {
      context.addIssue({
        code: 'custom',
        path: ['weekdays'],
        message: 'Choose at least one day',
      })
    }
    if (values.multipliers.length !== values.max_steps) {
      context.addIssue({
        code: 'custom',
        path: ['max_steps'],
        message: `Need exactly one multiplier per step (${String(values.max_steps)} steps, ${String(values.multipliers.length)} multipliers)`,
      })
    }
  })

export type SessionFormValues = z.infer<typeof sessionSchema>

export const EMPTY_SESSION: SessionFormValues = {
  name: '',
  enabled: true,
  asset: 'EURUSD',
  duration_s: 300,
  start_time: '11:00',
  end_time: '12:00',
  timezone: 'UTC',
  repeat: 'mon_fri',
  weekdays: WORK_DAYS,
  mode: 'sequential',
  max_open_pairs: 1,
  pause_s: 0,
  profit_target: '',
  loss_limit: '',
  max_pairs: '',
  strategy: 'flip_every_loss',
  base_stake: '1.00',
  max_steps: 3,
  multipliers: [{ value: '2.0' }, { value: '2.5' }, { value: '3.0' }],
  min_payout_pct: 80,
}

const sameDays = (a: readonly number[], b: readonly number[]) =>
  a.length === b.length && b.every((day) => a.includes(day))

function repeatOf(session: Session): SessionFormValues['repeat'] {
  if (session.repeat === 'once') return 'once'
  if (sameDays(session.weekdays, ALL_DAYS)) return 'every_day'
  if (sameDays(session.weekdays, WORK_DAYS)) return 'mon_fri'
  return 'chosen'
}

/** The API sends times as HH:MM:SS; the form works with HH:MM. */
const hhmm = (time: string) => time.slice(0, 5)

export function fromSession(session: Session): SessionFormValues {
  const strategy = session.strategy
  return {
    name: session.name,
    enabled: session.enabled,
    asset: session.asset,
    duration_s: session.duration_s,
    start_time: hhmm(session.start_time),
    end_time: hhmm(session.end_time),
    timezone: session.timezone,
    repeat: repeatOf(session),
    weekdays: session.weekdays,
    mode: session.mode,
    max_open_pairs: session.max_open_pairs,
    pause_s: session.pause_s,
    profit_target: session.profit_target ?? '',
    loss_limit: session.loss_limit ?? '',
    max_pairs: session.max_pairs === null ? '' : String(session.max_pairs),
    strategy: strategy?.strategy ?? EMPTY_SESSION.strategy,
    base_stake: strategy?.base_stake ?? EMPTY_SESSION.base_stake,
    max_steps: strategy?.max_steps ?? EMPTY_SESSION.max_steps,
    multipliers: strategy
      ? strategy.multipliers.map((value) => ({ value }))
      : EMPTY_SESSION.multipliers,
    min_payout_pct: strategy?.min_payout_pct ?? EMPTY_SESSION.min_payout_pct,
  }
}

function daysOf(values: SessionFormValues): number[] {
  switch (values.repeat) {
    case 'once':
      return []
    case 'every_day':
      return ALL_DAYS
    case 'mon_fri':
      return WORK_DAYS
    case 'chosen':
      return [...values.weekdays].sort((a, b) => a - b)
  }
}

export function toInput(values: SessionFormValues): SessionInput {
  const [base = values.asset, otc = ''] = values.asset.trim().split(/(?=_otc$)/i)
  return {
    name: values.name,
    enabled: values.enabled,
    // the base of the name is upper case (EURUSD); the suffix is written as Quotex does
    asset: `${base.toUpperCase()}${otc.toLowerCase()}`,
    duration_s: values.duration_s,
    start_time: values.start_time,
    end_time: values.end_time,
    timezone: values.timezone,
    repeat: values.repeat === 'once' ? 'once' : 'weekdays',
    weekdays: daysOf(values),
    mode: values.mode,
    max_open_pairs: values.mode === 'every_candle' ? values.max_open_pairs : 1,
    pause_s: values.mode === 'sequential' ? values.pause_s : 0,
    profit_target: values.profit_target === '' ? null : values.profit_target,
    loss_limit: values.loss_limit === '' ? null : values.loss_limit,
    max_pairs: values.max_pairs === '' ? null : Number(values.max_pairs),
    strategy: {
      strategy: values.strategy,
      base_stake: values.base_stake,
      max_steps: values.max_steps,
      multipliers: values.multipliers.map((m) => m.value),
      min_payout_pct: values.min_payout_pct,
    },
  }
}

// --- plain-words checks ---

export interface WorstCase {
  /** The most one pair can have staked: both first trades, then every step of the chain that keeps losing. */
  perPair: number
  /** With every allowed pair open at once. */
  together: number
  pairsAtOnce: number
}

const up = (value: number) => Math.ceil(value * 100 - 1e-9) / 100

/** Money at risk, from the stakes alone (no payout): both legs open at the base stake and one of them
 *  loses through every step. Returns null while the stakes cannot be read. */
export function worstCase(values: SessionFormValues): WorstCase | null {
  const base = Number(values.base_stake)
  if (!Number.isFinite(base) || base <= 0) return null
  let steps = 0
  for (const m of values.multipliers) {
    const factor = Number(m.value)
    if (!Number.isFinite(factor) || factor <= 0) return null
    steps += factor
  }
  const follow = values.strategy === 'no_martingale' ? 0 : steps
  const perPair = up(base * (2 + follow))
  const pairsAtOnce = values.mode === 'every_candle' ? values.max_open_pairs : 1
  return { perPair, together: up(perPair * pairsAtOnce), pairsAtOnce }
}

/** Minutes east of UTC of a zone written as the form accepts it (`UTC-3`, `+05:30`, a zone name),
 *  now; null if it cannot be read. */
export function zoneOffsetMinutes(zone: string, at: Date = new Date()): number | null {
  const text = zone.trim()
  if (/^(utc|gmt|z)$/i.test(text)) return 0
  const fixed = /^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$/i.exec(text)
  if (fixed) {
    const minutes = Number(fixed[2]) * 60 + Number(fixed[3] ?? 0)
    return (fixed[1] === '-' ? -1 : 1) * minutes
  }
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: text, timeZoneName: 'longOffset' })
      .formatToParts(at)
      .find((part) => part.type === 'timeZoneName')?.value
    if (parts === undefined) return null
    if (parts === 'GMT') return 0
    const match = /^GMT([+-])(\d{2}):(\d{2})$/.exec(parts)
    if (!match) return null
    return (match[1] === '-' ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3]))
  } catch {
    return null
  }
}

/** Why the start time is not on a candle boundary, or null if it is (or cannot be told). Candles are
 *  counted from 00:00 UTC, so the start is converted to UTC first. */
export function boundaryWarning(values: SessionFormValues, at: Date = new Date()): string | null {
  const offset = zoneOffsetMinutes(values.timezone, at)
  const match = /^(\d{2}):(\d{2})$/.exec(values.start_time)
  if (offset === null || !match) return null
  const local = Number(match[1]) * 60 + Number(match[2])
  const utcMinutes = (((local - offset) % 1440) + 1440) % 1440
  const length = values.duration_s / 60
  if (utcMinutes % length === 0) return null
  const minutes = length >= 60 ? `${String(length / 60)}-hour` : `${String(length)}-minute`
  return `${values.start_time} is not on a ${minutes} candle boundary (candles start on the clock of UTC). The first trades would start mid-candle, and Quotex may give them a different expiry than the trade length.`
}

type FieldName = keyof SessionFormValues | `multipliers.${number}.value` | 'root'

/** Where a problem the server reports (`strategy.multipliers.1`) shows in the form. */
export function formFieldFor(serverField: string): FieldName {
  const path = serverField.replace(/^strategy\./, '')
  const multiplier = /^multipliers\.(\d+)$/.exec(path)
  if (multiplier) return `multipliers.${multiplier[1] ?? '0'}.value` as FieldName
  if (path === 'strategy') return 'max_steps'
  if (path in EMPTY_SESSION) return path as keyof SessionFormValues
  return 'root'
}

export interface ServerProblems {
  fields: { name: FieldName; message: string }[]
  message: string | null
}

/** Splits an API error into messages for specific fields and one general message. */
export function serverProblems(error: unknown): ServerProblems {
  if (!(error instanceof ApiError)) {
    return { fields: [], message: error instanceof Error ? error.message : 'Something went wrong.' }
  }
  if (Array.isArray(error.details)) {
    const fields: ServerProblems['fields'] = []
    for (const problem of error.details as unknown[]) {
      if (
        typeof problem === 'object' &&
        problem !== null &&
        'field' in problem &&
        'message' in problem &&
        typeof problem.field === 'string' &&
        typeof problem.message === 'string'
      ) {
        fields.push({ name: formFieldFor(problem.field), message: problem.message })
      }
    }
    if (fields.length > 0) return { fields, message: null }
  }
  return { fields: [], message: error.message }
}
