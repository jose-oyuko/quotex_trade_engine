import { describe, expect, it } from 'vitest'
import { makeMetrics, makeSummary } from '../test/fixtures'
import { readExpectation, sampleLabel, sampleNote } from './reportText'

describe('sampleNote', () => {
  it('warns hard about a tiny sample and softly about a small one, and is silent about a good one', () => {
    expect(sampleNote('tiny', 9)).toMatch(/Only 9 trades.*far too few/)
    expect(sampleNote('small', 25)).toMatch(/25 trades: a small sample.*hint, not a result/)
    expect(sampleNote('ok', 500)).toBeNull()
  })

  it('has a short label for each', () => {
    expect([sampleLabel('tiny'), sampleLabel('small'), sampleLabel('ok')]).toEqual([
      'too few trades',
      'small sample',
      'enough trades',
    ])
  })
})

describe('readExpectation', () => {
  const read = (verdict: string, z: number, edge: number) =>
    readExpectation(
      makeSummary({
        metrics: makeMetrics({ trades: 200, sample: 'ok', avg_payout_pct: 85 }),
        expectation: {
          breakeven_win_rate: 0.5405,
          actual_win_rate: 0.5405 + edge,
          edge,
          z_score: z,
          verdict: verdict as never,
        },
      }),
    )

  it('refuses to conclude from too few trades, and says how many to wait for', () => {
    const reading = readExpectation(makeSummary())
    expect(reading.headline).toBe('Not enough trades to tell (9).')
    expect(reading.detail).toContain('break even')
    expect(reading.detail).toContain('81.7%')
    expect(reading.detail).toMatch(/55\.[01]%/) // the break-even win rate at that payout
    expect(reading.detail).toContain('44.4%')
    expect(reading.detail).toContain('at least 30 finished trades')
  })

  it('says "indistinguishable from break-even" for a gap luck explains', () => {
    const reading = read('consistent_with_break_even', 0.8, 0.02)
    expect(reading.headline).toBe('Indistinguishable from break-even so far.')
    expect(reading.detail).toContain('0.8 standard errors')
    expect(reading.detail).toContain('does not show an advantage')
  })

  it('reports a real edge with a warning to confirm it', () => {
    const reading = read('above_break_even', 2.6, 0.06)
    expect(reading.headline).toMatch(/Above break-even/)
    expect(reading.detail).toContain('6.0% above')
    expect(reading.detail).toMatch(/confirm it holds/)
  })

  it('reports a real shortfall plainly: staking cannot fix it', () => {
    const reading = read('below_break_even', -3.1, -0.08)
    expect(reading.headline).toMatch(/Below break-even/)
    expect(reading.detail).toContain('8.0% below')
    expect(reading.detail).toContain('whatever the staking')
  })

  it('has a sentence for no trades at all', () => {
    const reading = readExpectation(
      makeSummary({
        metrics: makeMetrics({ trades: 0, wins: 0, losses: 0, win_rate: null, sample: 'tiny' }),
        expectation: {
          breakeven_win_rate: null,
          actual_win_rate: null,
          edge: null,
          z_score: null,
          verdict: 'not_enough_data',
        },
      }),
    )
    expect(reading.headline).toBe('No finished trades in this range yet.')
  })
})
