import { describe, expect, it } from 'vitest'
import type { PriceAsset } from '../../api/types'
import {
  coverage,
  emptyBacktest,
  parseMultipliers,
  runCount,
  runLabel,
  toInput,
  validate,
} from './backtestSchema'

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

  it('sends the trend settings and the second period (Phase 31)', () => {
    const values = {
      ...emptyBacktest(TODAY),
      opens: ['breakout' as const, 'window' as const],
      pattern_candles: '6',
      trend_max_candles: '',
      check_first_day: '2026-11-10',
      check_last_day: '2026-11-12',
    }
    expect(validate(values)).toEqual({})
    expect(runCount(values)).toBe(8) // 2 strategies x 2 ways x 2 periods
    const body = toInput(values)
    expect(body.opens).toEqual(['window', 'breakout']) // always in the same order
    expect(body.market).toMatchObject({ pattern: 'alternating', candles: 6, breakout_candles: 2 })
    expect(body.trend_max_candles).toBeNull()
    expect([body.check_first_day, body.check_last_day]).toEqual(['2026-11-10', '2026-11-12'])
    expect(toInput(emptyBacktest(TODAY)).check_first_day).toBeNull()
  })

  it('refuses no way of opening, half a second period, too many runs, bad trend settings', () => {
    const base = emptyBacktest(TODAY)
    expect(validate({ ...base, opens: [] }).opens).toBe('Choose at least one way to open pairs')
    expect(validate({ ...base, check_first_day: '2026-11-10' }).check_last_day).toMatch(
      /Choose the last day/,
    )
    const many = {
      ...base,
      opens: ['window' as const, 'breakout' as const],
      check_first_day: '2026-11-10',
      check_last_day: '2026-11-10',
      strategies: [...base.strategies, ...base.strategies],
    }
    expect(validate(many).strategies).toMatch(/At most 12 runs/)
    const bad = validate({
      ...base,
      opens: ['breakout'],
      pattern: 'mixed',
      pattern_candles: '4',
      misses: '3',
      trend_max_candles: '0',
    })
    expect(bad.misses).toBe('A whole number from 0 to 2')
    expect(bad.trend_max_candles).toMatch(/whole number of candles/)
    // the trend settings are not checked when no pair opens after a breakout
    expect(validate({ ...base, pattern_candles: 'x' }).pattern_candles).toBeUndefined()
  })

  it('names each run by strategy, way of opening and period when there are several', () => {
    const run = {
      strategy: 'martingale' as const,
      max_steps: 2,
      multipliers: ['2', '4'],
      opens: 'window' as const,
      period: 1,
    }
    expect(runLabel(run, [run])).toBe('Martingale ×2, 4')
    const trend = { ...run, opens: 'breakout' as const, period: 2 }
    expect(runLabel(run, [run, trend])).toBe('Martingale ×2, 4 · always on · period 1')
    expect(runLabel(trend, [run, trend])).toBe('Martingale ×2, 4 · after a breakout · period 2')
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
