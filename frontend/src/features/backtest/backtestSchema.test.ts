import { describe, expect, it } from 'vitest'
import type { PriceAsset } from '../../api/types'
import { coverage, emptyBacktest, parseMultipliers, toInput, validate } from './backtestSchema'

const TODAY = new Date('2026-11-19T12:00:00Z')

describe('the backtest form rules', () => {
  it('starts with yesterday, two strategies and the measured assumptions', () => {
    const values = emptyBacktest(TODAY)
    expect(values.first_day).toBe('2026-11-18')
    expect(values.payout_pct).toBe('88')
    expect(validate(values)).toEqual({})
  })

  it('turns the form into the API body, one multiplier per step', () => {
    const body = toInput({ ...emptyBacktest(TODAY), max_pairs: '10', profit_target: '' })
    expect(body.strategies).toEqual([
      { strategy: 'martingale', max_steps: 3, multipliers: ['2', '4', '8'] },
      {
        strategy: 'growing_flip',
        max_steps: 8,
        multipliers: ['2', '4', '8', '16', '32', '64', '128', '256'],
      },
    ])
    expect(body.max_pairs).toBe(10)
    expect(body.profit_target).toBeNull()
    expect(body.name).toBeNull()
  })

  it('reads multipliers separated by commas or spaces', () => {
    expect(parseMultipliers('2, 2.5 3,,4')).toEqual(['2', '2.5', '3', '4'])
    expect(parseMultipliers('')).toEqual([])
  })

  it('refuses a 9th growing flip step, steps on no martingale, and bad multipliers', () => {
    const base = emptyBacktest(TODAY)
    const errors = validate({
      ...base,
      strategies: [
        { strategy: 'growing_flip', multipliers: '2 2 2 2 2 2 2 2 2' },
        { strategy: 'no_martingale', multipliers: '2' },
        { strategy: 'martingale', multipliers: '2, x' },
      ],
    })
    expect(errors['strategies.0']).toBe('Growing flip has at most 8 steps (9 trades in all)')
    expect(errors['strategies.1']).toBe('No martingale has no steps: leave the multipliers empty')
    expect(errors['strategies.2']).toBe(
      'Multipliers are numbers like 2 or 2.5, separated by commas',
    )
  })

  it('checks the days, the window and the amounts', () => {
    const errors = validate({
      ...emptyBacktest(TODAY),
      first_day: '2026-11-10',
      last_day: '2026-11-01',
      end_time: '10:00',
      base_stake: '0',
      payout_pct: '120',
      weekdays: [],
      strategies: [],
    })
    expect(errors.last_day).toBe('The last day must not be before the first')
    expect(errors.end_time).toBe('The window needs a start and an end that are different')
    expect(errors.base_stake).toBeDefined()
    expect(errors.payout_pct).toBeDefined()
    expect(errors.weekdays).toBeDefined()
    expect(errors.strategies).toBe('Add at least one strategy')
    const long = validate({
      ...emptyBacktest(TODAY),
      first_day: '2026-01-01',
      last_day: '2026-11-01',
    })
    expect(long.last_day).toBe('At most 92 days per backtest')
  })

  it('says whether the stored prices cover the chosen days', () => {
    const held: PriceAsset[] = [
      {
        asset: '1HZ75V',
        ticks: 1,
        first: null,
        last: null,
        ranges: [{ start: '2026-11-17T00:00:00Z', end: '2026-11-18T23:59:59Z' }],
      },
    ]
    expect(coverage(held, '1HZ75V', '2026-11-18', '2026-11-18')).toBe('all')
    expect(coverage(held, '1HZ75V', '2026-11-18', '2026-11-19')).toBe('part')
    expect(coverage(held, '1HZ75V', '2026-11-20', '2026-11-21')).toBe('none')
    expect(coverage(held, 'R_75', '2026-11-18', '2026-11-18')).toBe('none')
  })
})
