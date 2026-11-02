import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { makeGroup } from '../../test/fixtures'
import {
  EMPTY_GROUP,
  formFieldFor,
  fromGroup,
  groupSchema,
  serverProblems,
  toCreate,
  toUpdate,
  type GroupFormValues,
} from './groupSchema'

const valid = (overrides: Partial<GroupFormValues> = {}): GroupFormValues => ({
  ...EMPTY_GROUP,
  title: 'Alpha',
  telegram_chat_id: '-1001234567890',
  ...overrides,
})

/** The message the form shows per field: the first problem found (as react-hook-form does). */
function problems(values: GroupFormValues): Record<string, string> {
  const result = groupSchema.safeParse(values)
  const found: Record<string, string> = {}
  if (!result.success) {
    for (const issue of result.error.issues) found[issue.path.join('.')] ??= issue.message
  }
  return found
}

describe('the group schema', () => {
  it('accepts the default settings with a name and a chat id', () => {
    expect(problems(valid())).toEqual({})
  })

  it('needs exactly one multiplier per step', () => {
    expect(problems(valid({ max_steps: 3, multipliers: [{ value: '2' }] }))).toHaveProperty(
      'max_steps',
      expect.stringContaining('one multiplier per step'),
    )
    expect(
      problems(valid({ max_steps: 1, multipliers: [{ value: '2' }, { value: '3' }] })),
    ).toHaveProperty('max_steps')
    expect(problems(valid({ max_steps: 0, multipliers: [] }))).toEqual({})
  })

  it.each(['0', '0.0', '-1', 'abc', '', '2,5', '1001', '2.12345'])(
    'refuses %j as a multiplier and names which one',
    (bad) => {
      const result = problems(
        valid({ max_steps: 2, multipliers: [{ value: '2' }, { value: bad }] }),
      )
      expect(Object.keys(result)).toEqual(['multipliers.1.value'])
    },
  )

  it.each(['2', '2.5', '0.5', '1000', '3.1416'])('accepts %j as a multiplier', (good) => {
    expect(problems(valid({ max_steps: 1, multipliers: [{ value: good }] }))).toEqual({})
  })

  it.each([
    ['0', 'greater than 0'],
    ['-1', '2 decimals'],
    ['1.005', '2 decimals'],
    ['abc', '2 decimals'],
    ['', '2 decimals'],
    ['1000001', 'too large'],
  ])('refuses a base stake of %j', (stake, fragment) => {
    expect(problems(valid({ base_stake: stake }))).toHaveProperty(
      'base_stake',
      expect.stringContaining(fragment),
    )
  })

  it.each(['1', '1.5', '0.01', '1000000'])('accepts a base stake of %s', (stake) => {
    expect(problems(valid({ base_stake: stake }))).toEqual({})
  })

  it.each([-1, 21, 1.5, Number.NaN])('refuses %s steps', (steps) => {
    expect(problems(valid({ max_steps: steps, multipliers: [] }))).toHaveProperty('max_steps')
  })

  it.each([-1, 101, 50.5, Number.NaN])('refuses a minimum payout of %s', (pct) => {
    expect(problems(valid({ min_payout_pct: pct }))).toHaveProperty('min_payout_pct')
  })

  it.each(['0', 'abc', '1.5', '', '99999999999999999999'])('refuses a chat id of %j', (id) => {
    expect(problems(valid({ telegram_chat_id: id }))).toHaveProperty('telegram_chat_id')
  })

  it('needs a name and a time zone', () => {
    expect(problems(valid({ title: '   ' }))).toHaveProperty('title')
    expect(problems(valid({ title: 'x'.repeat(201) }))).toHaveProperty('title')
    expect(problems(valid({ timezone: ' ' }))).toHaveProperty('timezone')
  })
})

describe('turning the form into requests and back', () => {
  it('builds the create request with the chat id as a number and money as text', () => {
    expect(toCreate(valid({ base_stake: '2.50' }))).toEqual({
      telegram_chat_id: -1001234567890,
      title: 'Alpha',
      enabled: true,
      settings: {
        parser: 'legacy_v1',
        asset_suffix_mode: 'otc',
        timezone: 'UTC-3',
        strategy: 'martingale',
        base_stake: '2.50',
        max_steps: 3,
        multipliers: ['2.0', '2.5', '3.0'],
        min_payout_pct: 80,
      },
    })
  })

  it('builds an update request without a chat id', () => {
    const update = toUpdate(valid())
    expect(update).not.toHaveProperty('telegram_chat_id')
    expect(update.settings.multipliers).toEqual(['2.0', '2.5', '3.0'])
  })

  it('fills the form from a group, and round-trips', () => {
    const group = makeGroup()
    const values = fromGroup(group)
    expect(values.multipliers).toEqual([{ value: '2.0' }, { value: '2.5' }, { value: '3.0' }])
    expect(values.telegram_chat_id).toBe('-1001')
    expect(toUpdate(values).settings.base_stake).toBe('1.00')
  })

  it('copes with a group that has no settings yet', () => {
    const values = fromGroup(makeGroup({ settings: null, title: 'Bare' }))
    expect(values.title).toBe('Bare')
    expect(values.strategy).toBe(EMPTY_GROUP.strategy)
  })
})

describe('server problems', () => {
  it('maps the server’s field names to the form’s', () => {
    expect(formFieldFor('settings.base_stake')).toBe('base_stake')
    expect(formFieldFor('settings.multipliers.1')).toBe('multipliers.1.value')
    expect(formFieldFor('settings')).toBe('max_steps')
    expect(formFieldFor('telegram_chat_id')).toBe('telegram_chat_id')
    expect(formFieldFor('something.else')).toBe('root')
  })

  it('splits a validation error into field messages', () => {
    const error = new ApiError(422, 'validation_error', 'The request is not valid.', [
      { field: 'settings.multipliers.0', message: 'Input should be greater than 0' },
      { field: 'title', message: 'too short' },
    ])
    expect(serverProblems(error)).toEqual({
      fields: [
        { name: 'multipliers.0.value', message: 'Input should be greater than 0' },
        { name: 'title', message: 'too short' },
      ],
      message: null,
    })
  })

  it('puts a duplicate chat on the chat id field and anything else in one message', () => {
    expect(serverProblems(new ApiError(409, 'group_exists', 'chat exists')).fields).toEqual([
      { name: 'telegram_chat_id', message: 'chat exists' },
    ])
    expect(serverProblems(new ApiError(502, 'quotex_error', 'broken'))).toEqual({
      fields: [],
      message: 'broken',
    })
    expect(serverProblems(new Error('Cannot reach the backend. Is it running?')).message).toBe(
      'Cannot reach the backend. Is it running?',
    )
  })
})
