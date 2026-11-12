import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import { makeSession } from '../../test/fixtures'
import {
  EMPTY_SESSION,
  boundaryWarning,
  fromSession,
  serverProblems,
  sessionSchema,
  toInput,
  worstCase,
  zoneOffsetMinutes,
  type SessionFormValues,
} from './sessionSchema'

const valid: SessionFormValues = { ...EMPTY_SESSION, name: 'London open' }
const problems = (values: SessionFormValues) => {
  const result = sessionSchema.safeParse(values)
  return result.success ? [] : result.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`)
}

describe('the session form rules', () => {
  it('accepts a complete session', () => {
    expect(problems(valid)).toEqual([])
  })

  it('wants a name, a real asset name and a trade length Quotex offers', () => {
    expect(problems({ ...valid, name: '  ' })).toEqual(['name: Give the session a name'])
    expect(problems({ ...valid, asset: 'eur/usd' })[0]).toMatch(/^asset: Use the Quotex name/)
    expect(problems({ ...valid, asset: 'eurusd_otc' })).toEqual([]) // spelt as typed, fixed on send
    expect(problems({ ...valid, duration_s: 45 })).toEqual(['duration_s: Choose a trade length'])
  })

  it('wants times like 11:00 that differ, and at least one day when the days are chosen', () => {
    expect(problems({ ...valid, start_time: '25:00' })[0]).toMatch(/^start_time: Use a time/)
    expect(problems({ ...valid, end_time: '11:00' })).toEqual([
      'end_time: The window needs a start and an end that are different',
    ])
    expect(problems({ ...valid, end_time: '01:00', start_time: '23:00' })).toEqual([]) // midnight
    expect(problems({ ...valid, repeat: 'chosen', weekdays: [] })).toEqual([
      'weekdays: Choose at least one day',
    ])
    expect(problems({ ...valid, repeat: 'chosen', weekdays: [2] })).toEqual([])
  })

  it('treats a target, a limit and a pair count as optional, but sensible when given', () => {
    expect(problems({ ...valid, profit_target: '', loss_limit: '', max_pairs: '' })).toEqual([])
    expect(problems({ ...valid, profit_target: '0' })).toEqual([
      'profit_target: Must be greater than 0',
    ])
    expect(problems({ ...valid, loss_limit: '1.234' })[0]).toMatch(/at most 2 decimals/)
    expect(problems({ ...valid, max_pairs: '0' })[0]).toMatch(/^max_pairs/)
    expect(problems({ ...valid, max_pairs: '12' })).toEqual([])
  })

  it('wants one multiplier per step and keeps the number of open pairs between 1 and 50', () => {
    expect(problems({ ...valid, max_steps: 2 })[0]).toMatch(/Need exactly one multiplier per step/)
    expect(problems({ ...valid, max_open_pairs: 0 })[0]).toMatch(/^max_open_pairs/)
    expect(problems({ ...valid, max_open_pairs: 51 })[0]).toMatch(/^max_open_pairs/)
    expect(problems({ ...valid, pause_s: -1 })[0]).toMatch(/^pause_s/)
  })
})

describe('what is sent and what is shown back', () => {
  it('sends the repeat choice as the API names it', () => {
    expect(toInput({ ...valid, repeat: 'once' })).toMatchObject({ repeat: 'once', weekdays: [] })
    expect(toInput({ ...valid, repeat: 'every_day' })).toMatchObject({
      repeat: 'weekdays',
      weekdays: [0, 1, 2, 3, 4, 5, 6],
    })
    expect(toInput({ ...valid, repeat: 'mon_fri' })).toMatchObject({ weekdays: [0, 1, 2, 3, 4] })
    expect(toInput({ ...valid, repeat: 'chosen', weekdays: [4, 1] })).toMatchObject({
      weekdays: [1, 4],
    })
  })

  it('writes the asset the way Quotex does and drops what the mode does not use', () => {
    expect(toInput({ ...valid, asset: ' eurusd_OTC ' }).asset).toBe('EURUSD_otc')
    const sequential = toInput({ ...valid, mode: 'sequential', max_open_pairs: 7, pause_s: 90 })
    expect([sequential.max_open_pairs, sequential.pause_s]).toEqual([1, 90])
    const candle = toInput({ ...valid, mode: 'every_candle', max_open_pairs: 3, pause_s: 90 })
    expect([candle.mode, candle.max_open_pairs, candle.pause_s]).toEqual(['every_candle', 3, 0])
  })

  it('sends nothing for a target left empty', () => {
    const input = toInput({ ...valid, profit_target: '', loss_limit: '5.00', max_pairs: '' })
    expect([input.profit_target, input.loss_limit, input.max_pairs]).toEqual([null, '5.00', null])
  })

  it('reads a saved session back into the form, recognising the day presets', () => {
    expect(fromSession(makeSession())).toMatchObject({
      start_time: '11:00',
      end_time: '12:00',
      repeat: 'mon_fri',
      profit_target: '10.00',
      max_pairs: '',
      multipliers: [{ value: '2.0' }, { value: '3.0' }],
    })
    expect(fromSession(makeSession({ weekdays: [0, 1, 2, 3, 4, 5, 6] })).repeat).toBe('every_day')
    expect(fromSession(makeSession({ weekdays: [1, 3] })).repeat).toBe('chosen')
    expect(fromSession(makeSession({ repeat: 'once', weekdays: [] })).repeat).toBe('once')
    expect(fromSession(makeSession({ max_pairs: 8 })).max_pairs).toBe('8')
  })

  it('round-trips a session through the form', () => {
    const session = makeSession({ mode: 'every_candle', max_open_pairs: 3, weekdays: [1, 3] })
    const input = toInput(fromSession(session))
    expect(input).toMatchObject({ mode: 'every_candle', max_open_pairs: 3, weekdays: [1, 3] })
    expect(input.strategy.multipliers).toEqual(['2.0', '3.0'])
  })
})

describe('the most that can be at stake', () => {
  it('adds both first trades and every step of the leg that keeps losing', () => {
    // base 1.00 and multipliers 2.0 and 3.0: two first trades (2) plus the steps (2 + 3) = 7
    expect(
      worstCase({ ...valid, max_steps: 2, multipliers: [{ value: '2.0' }, { value: '3.0' }] }),
    ).toEqual({ perPair: 7, together: 7, pairsAtOnce: 1 })
  })

  it('multiplies by the pairs that may be open at once, only in every-candle mode', () => {
    const base = { ...valid, max_steps: 1, multipliers: [{ value: '2.5' }], max_open_pairs: 4 }
    expect(worstCase({ ...base, mode: 'sequential' })?.together).toBe(4.5)
    expect(worstCase({ ...base, mode: 'every_candle' })).toEqual({
      perPair: 4.5,
      together: 18,
      pairsAtOnce: 4,
    })
  })

  it('counts only the two first trades without a martingale, and rounds up to the cent', () => {
    expect(worstCase({ ...valid, strategy: 'no_martingale', base_stake: '2.50' })?.perPair).toBe(5)
    expect(
      worstCase({ ...valid, base_stake: '0.33', max_steps: 1, multipliers: [{ value: '1.5' }] })
        ?.perPair,
    ).toBe(1.16) // 0.33 * 3.5 = 1.155
  })

  it('says nothing while the stakes cannot be read', () => {
    expect(worstCase({ ...valid, base_stake: 'abc' })).toBeNull()
    expect(worstCase({ ...valid, multipliers: [{ value: 'x' }] })).toBeNull()
  })
})

describe('the candle boundary warning', () => {
  const at = new Date('2026-11-02T10:00:00Z')

  it('reads the zones the form accepts', () => {
    expect(zoneOffsetMinutes('UTC', at)).toBe(0)
    expect(zoneOffsetMinutes('UTC-3', at)).toBe(-180)
    expect(zoneOffsetMinutes('GMT+5:30', at)).toBe(330)
    expect(zoneOffsetMinutes('+02:00', at)).toBe(120)
    expect(zoneOffsetMinutes('Africa/Nairobi', at)).toBe(180)
    expect(zoneOffsetMinutes('Mars/Olympus', at)).toBeNull()
  })

  it('is quiet when the start is on a candle of the trade length, counting from UTC', () => {
    expect(boundaryWarning({ ...valid, start_time: '11:00' }, at)).toBeNull()
    expect(boundaryWarning({ ...valid, start_time: '11:05' }, at)).toBeNull()
    // 08:00 in UTC-3 is 11:00 UTC
    expect(boundaryWarning({ ...valid, timezone: 'UTC-3', start_time: '08:00' }, at)).toBeNull()
    expect(boundaryWarning({ ...valid, timezone: 'foo/bar', start_time: '11:02' }, at)).toBeNull()
  })

  it('warns, in words, when it is not', () => {
    const text = boundaryWarning({ ...valid, start_time: '11:02' }, at)
    expect(text).toMatch(/11:02 is not on a 5-minute candle boundary/)
    expect(boundaryWarning({ ...valid, duration_s: 3600, start_time: '11:30' }, at)).toMatch(
      /1-hour candle/,
    )
    // 08:30 in UTC+5:30 is 03:00 UTC: on an M5 boundary
    expect(boundaryWarning({ ...valid, timezone: 'UTC+5:30', start_time: '08:30' }, at)).toBeNull()
  })
})

describe('what the server says', () => {
  it('puts a problem on the field it is about', () => {
    const error = new ApiError(422, 'validation_error', 'The request is not valid.', [
      { field: 'strategy.multipliers.1', message: 'must be greater than 0' },
      { field: 'start_time', message: 'bad time' },
    ])
    expect(serverProblems(error)).toEqual({
      fields: [
        { name: 'multipliers.1.value', message: 'must be greater than 0' },
        { name: 'start_time', message: 'bad time' },
      ],
      message: null,
    })
  })

  it('keeps a general message (an overlap, say) for the top of the form', () => {
    const error = new ApiError(409, 'session_overlap', 'The window overlaps the one of "Night"')
    expect(serverProblems(error)).toEqual({
      fields: [],
      message: 'The window overlaps the one of "Night"',
    })
    expect(serverProblems(new Error('offline')).message).toBe('offline')
  })
})
