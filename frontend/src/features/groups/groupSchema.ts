// What the group form accepts. It mirrors the backend's rules (backend/app/api/schemas/groups.py)
// so a mistake is caught while typing; the server checks everything again and its answer is shown
// on the same fields if it disagrees.
import { z } from 'zod'
import { ApiError } from '../../api/client'
import type { Group, GroupCreate, GroupUpdate } from '../../api/types'

export const MAX_STEPS = 20
export const DEFAULT_MULTIPLIER = '2.0'

export const STRATEGIES = [
  {
    value: 'no_martingale',
    label: 'No martingale',
    help: 'Every signal is traded once at the base stake. There are no follow-ups.',
  },
  {
    value: 'martingale',
    label: 'Martingale',
    help: 'After a loss the same direction is traded again, with the stake multiplied by that step’s multiplier.',
  },
  {
    value: 'flip_every_loss',
    label: 'Flip every loss',
    help: 'After a loss the opposite direction is traded, then the original, and so on. New signals are ignored while a chain runs (unless the opposite pair below is allowed).',
  },
  {
    value: 'two_step_flip',
    label: 'Two-step flip',
    help: 'The direction changes after every second loss. New signals are ignored while a chain runs (unless the opposite pair below is allowed).',
  },
] as const

/** The strategies that run one chain at a time, and so may allow the opposite pair. */
export const FLIP_STRATEGIES: readonly string[] = ['flip_every_loss', 'two_step_flip']

export const SUFFIX_MODES = [
  { value: 'otc', label: 'Always OTC (EURUSD becomes EURUSD_otc)' },
  { value: 'none', label: 'Never OTC (as written)' },
  { value: 'auto', label: 'Automatic (OTC only when the message says so)' },
] as const

const stake = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, 'Use a number with at most 2 decimals, like 1.50')
  .refine((value) => Number(value) > 0, 'Must be greater than 0')
  .refine((value) => Number(value) <= 1_000_000, 'That is too large')

const multiplier = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,4})?$/, 'Use a number like 2 or 2.5')
  .refine((value) => Number(value) > 0, 'Must be greater than 0')
  .refine((value) => Number(value) <= 1000, 'That is too large')

export const groupSchema = z
  .object({
    title: z.string().trim().min(1, 'Give the group a name').max(200, 'At most 200 characters'),
    telegram_chat_id: z
      .string()
      .trim()
      .regex(/^-?\d+$/, 'The chat id is a whole number, like -1001234567890')
      .refine((value) => Number.isSafeInteger(Number(value)), 'That number is too large')
      .refine((value) => Number(value) !== 0, 'The chat id cannot be 0'),
    enabled: z.boolean(),
    parser: z.string().trim().min(1, 'Choose a parser'),
    asset_suffix_mode: z.enum(['otc', 'none', 'auto']),
    timezone: z.string().trim().min(1, 'Enter a time zone, like UTC-3').max(64),
    strategy: z.enum(['no_martingale', 'martingale', 'flip_every_loss', 'two_step_flip']),
    base_stake: stake,
    max_steps: z
      .number({ error: `Enter a whole number from 0 to ${String(MAX_STEPS)}` })
      .int(`Enter a whole number from 0 to ${String(MAX_STEPS)}`)
      .min(0, 'Cannot be negative')
      .max(MAX_STEPS, `At most ${String(MAX_STEPS)} steps`),
    multipliers: z.array(z.object({ value: multiplier })),
    min_payout_pct: z
      .number({ error: 'Enter a whole number from 0 to 100' })
      .int('Enter a whole number from 0 to 100')
      .min(0, 'At least 0')
      .max(100, 'At most 100'),
    allow_opposite_pair: z.boolean(),
  })
  .superRefine((values, context) => {
    if (values.multipliers.length !== values.max_steps) {
      context.addIssue({
        code: 'custom',
        path: ['max_steps'],
        message: `Need exactly one multiplier per step (${String(values.max_steps)} steps, ${String(values.multipliers.length)} multipliers)`,
      })
    }
  })

export type GroupFormValues = z.infer<typeof groupSchema>

export const EMPTY_GROUP: GroupFormValues = {
  title: '',
  telegram_chat_id: '',
  enabled: true,
  parser: 'legacy_v1',
  asset_suffix_mode: 'otc',
  timezone: 'UTC-3',
  strategy: 'martingale',
  base_stake: '1.00',
  max_steps: 3,
  multipliers: [{ value: '2.0' }, { value: '2.5' }, { value: '3.0' }],
  min_payout_pct: 80,
  allow_opposite_pair: false,
}

export function fromGroup(group: Group): GroupFormValues {
  const settings = group.settings
  if (settings === null) return { ...EMPTY_GROUP, title: group.title, enabled: group.enabled }
  return {
    title: group.title,
    telegram_chat_id: String(group.telegram_chat_id),
    enabled: group.enabled,
    parser: settings.parser,
    asset_suffix_mode: settings.asset_suffix_mode,
    timezone: settings.timezone,
    strategy: settings.strategy,
    base_stake: settings.base_stake,
    max_steps: settings.max_steps,
    multipliers: settings.multipliers.map((value) => ({ value })),
    min_payout_pct: settings.min_payout_pct,
    allow_opposite_pair: settings.allow_opposite_pair,
  }
}

function settingsOf(values: GroupFormValues) {
  return {
    parser: values.parser,
    asset_suffix_mode: values.asset_suffix_mode,
    timezone: values.timezone,
    strategy: values.strategy,
    base_stake: values.base_stake,
    max_steps: values.max_steps,
    multipliers: values.multipliers.map((m) => m.value),
    min_payout_pct: values.min_payout_pct,
    // only the flip strategies have the setting; the server refuses it for the others
    allow_opposite_pair: values.allow_opposite_pair && FLIP_STRATEGIES.includes(values.strategy),
  }
}

export function toCreate(values: GroupFormValues): GroupCreate {
  return {
    telegram_chat_id: Number(values.telegram_chat_id),
    title: values.title,
    enabled: values.enabled,
    settings: settingsOf(values),
  }
}

export function toUpdate(values: GroupFormValues): GroupUpdate {
  return { title: values.title, enabled: values.enabled, settings: settingsOf(values) }
}

type FieldName = keyof GroupFormValues | `multipliers.${number}.value` | `root`

/** Where a problem the server reports (`settings.multipliers.1`) shows in the form. */
export function formFieldFor(serverField: string): FieldName {
  const path = serverField.replace(/^settings\./, '')
  const multiplier = /^multipliers\.(\d+)$/.exec(path)
  if (multiplier) return `multipliers.${multiplier[1] ?? '0'}.value` as FieldName
  if (path === 'settings') return 'max_steps' // the "one multiplier per step" rule
  if (path in EMPTY_GROUP) return path as keyof GroupFormValues
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
  if (error.code === 'group_exists') {
    return {
      fields: [{ name: 'telegram_chat_id', message: error.message }],
      message: null,
    }
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
