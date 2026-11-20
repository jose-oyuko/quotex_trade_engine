import { describe, expect, it } from 'vitest'
import type { MarketStats, Rate, Scan } from '../../api/types'
import {
  CHUNK,
  candlesText,
  chunkOf,
  chunkSpan,
  chunksAround,
  differs,
  emptyScan,
  epochOfInput,
  inputOf,
  isoOf,
  lengthLabel,
  statsText,
  toScanInput,
  trendAfter,
  validateScan,
} from './marketSchema'

const T = 1_794_441_600 // 2026-11-12T00:00:00Z

const rate = (hits: number, total: number, low: number, high: number): Rate => ({
  hits,
  total,
  share: total ? hits / total : 0,
  low,
  high,
})

describe('the chart’s chunks', () => {
  it('cover a period with one more chunk on each side', () => {
    const chunk = chunkOf(T, 60)
    expect(chunkSpan(chunk, 60)[0]).toBeLessThanOrEqual(T)
    expect(chunkSpan(chunk, 60)[1] - chunkSpan(chunk, 60)[0]).toBe(CHUNK * 60)
    expect(chunksAround(T, T + 10, 60)).toEqual([chunk - 1, chunk, chunk + 1])
    expect(lengthLabel(300)).toBe('M5')
    expect(lengthLabel(90)).toBe('90 s')
  })
})

describe('times', () => {
  it('are UTC in the date-and-time fields', () => {
    expect(inputOf(T)).toBe('2026-11-12T00:00')
    expect(epochOfInput('2026-11-12T00:00')).toBe(T)
    expect(epochOfInput('')).toBeNull()
    expect(isoOf(T)).toBe('2026-11-12T00:00:00Z')
  })
})

describe('the scan form', () => {
  it('starts with the last day stored and the owner’s definition', () => {
    const values = emptyScan(T)
    expect(values.start).toBe('2026-11-11T00:00')
    expect(values.end).toBe('2026-11-12T00:00')
    expect(values.pattern).toBe('alternating')
    expect(values.candles).toBe('5')
    expect(values.breakout_candles).toBe('2')
    expect(validateScan(values)).toEqual({})
  })

  it('refuses what the server would refuse', () => {
    const values = emptyScan(T)
    expect(validateScan({ ...values, candles: '1', breakout_candles: '0' })).toEqual({
      candles: 'From 2 to 50 candles',
      breakout_candles: 'From 1 to 10 candles',
    })
    expect(validateScan({ ...values, end: values.start }).end).toBe(
      'The end must come after the start',
    )
    expect(validateScan({ ...values, start: '2026-09-01T00:00' }).end).toBe('At most 31 days')
    expect(validateScan({ ...values, pattern: 'mixed', candles: '5', misses: '4' }).misses).toBe(
      'From 0 to 3',
    )
    expect(validateScan({ ...values, pattern: 'tight', width: '0' }).width).toBeDefined()
    expect(validateScan({ ...values, pattern: 'choppy', net_share: '1' }).net_share).toBeDefined()
    // a setting of another pattern is not checked
    expect(validateScan({ ...values, width: 'x' })).toEqual({})
  })

  it('sends numbers and UTC times', () => {
    const input = toScanInput('1HZ75V', 300, { ...emptyScan(T), breakout_by: 'touch' })
    expect(input).toEqual({
      asset: '1HZ75V',
      length: 300,
      deep: 6,
      start: '2026-11-11T00:00:00Z',
      end: '2026-11-12T00:00:00Z',
      rules: {
        pattern: 'alternating',
        candles: 5,
        misses: 1,
        width: 2,
        net_share: 0.2,
        breakout_candles: 2,
        breakout_by: 'touch',
      },
    })
  })
})

describe('the statistics in words', () => {
  const spread = (median: number) => ({
    count: 10,
    mean: median,
    median,
    q1: 1,
    q3: 9,
    longest: 20,
  })
  const stats: MarketStats = {
    candles: 1000,
    consolidations: 30,
    breakouts: 29,
    in_consolidation: 0.3,
    trend_wait: spread(22),
    any_wait: spread(21),
    first_with: rate(14, 29, 0.31, 0.66),
    trend_with: rate(400, 800, 0.46, 0.53),
    break_even: 0.5319,
    deep: 6,
    deep_any: rate(35, 1000, 0.025, 0.048),
    deep_trend: rate(30, 780, 0.027, 0.054),
    deep_consolidation: rate(3, 150, 0.007, 0.057),
    described: rate(90, 100, 0.83, 0.94),
  }

  it('compares trends with any moment and says when it is noise', () => {
    const lines = statsText(stats, 60)
    expect(lines[0]).toBe('30 consolidations (29 broke out); 30.0% of the time was inside one.')
    expect(lines[1]).toContain('median 22 candles (22 min); from any moment, after 21 candles')
    expect(lines[2]).toContain('48.3% of the time (likely 31.0% to 66.0%)')
    expect(lines[2]).toContain('53.2%')
    expect(lines[3]).toContain('no real difference')
    expect(lines[4]).toContain('90.0% of the candles')
    expect(differs(rate(1, 100, 0.001, 0.05), rate(30, 100, 0.2, 0.4))).toBe(true)
    expect(candlesText(30, 300)).toBe('30 candles (2.5 h)')
    expect(candlesText(30, 3600)).toBe('30 candles (30.0 h)')
  })
})

describe('the trend after a consolidation', () => {
  it('is the one starting when its breakout was known', () => {
    const scan = {
      consolidations: [
        { first: '2026-11-12T00:00:00Z', breakout: { known: '2026-11-12T00:07:00Z' } },
        { first: '2026-11-12T00:20:00Z', breakout: null },
      ],
      trends: [{ start: '2026-11-12T00:07:00Z', end: '2026-11-12T00:20:00Z' }],
    } as unknown as Scan
    const found = trendAfter(scan)
    expect(found.get(0)?.end).toBe('2026-11-12T00:20:00Z')
    expect(found.has(1)).toBe(false)
  })
})
