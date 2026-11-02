import { describe, expect, it } from 'vitest'
import { browserOffsetMinutes, rangeToIso } from './dates'

// "Now" is Tue 3 Nov 2026 02:30 UTC. For someone at UTC-3 that is still Mon 2 Nov, 23:30.
const NOW = new Date('2026-11-03T02:30:00Z')

describe('rangeToIso', () => {
  it('has no limits for "all time"', () => {
    expect(rangeToIso({ preset: 'all' }, NOW, 0)).toEqual({})
  })

  it('"today" is the owner’s calendar day, not the UTC day', () => {
    expect(rangeToIso({ preset: 'today' }, NOW, 0)).toEqual({
      from: '2026-11-03T00:00:00.000Z',
      to: '2026-11-04T00:00:00.000Z',
    })
    // at UTC-3 it is still Monday: Mon 00:00 local = 03:00 UTC
    expect(rangeToIso({ preset: 'today' }, NOW, -180)).toEqual({
      from: '2026-11-02T03:00:00.000Z',
      to: '2026-11-03T03:00:00.000Z',
    })
    // at UTC+5:30 it is already Tuesday 08:00
    expect(rangeToIso({ preset: 'today' }, NOW, 330)).toEqual({
      from: '2026-11-02T18:30:00.000Z',
      to: '2026-11-03T18:30:00.000Z',
    })
  })

  it('"last 7 days" includes today and the six days before it', () => {
    expect(rangeToIso({ preset: '7' }, NOW, 0)).toEqual({
      from: '2026-10-28T00:00:00.000Z',
      to: '2026-11-04T00:00:00.000Z',
    })
    expect(rangeToIso({ preset: '30' }, NOW, 0)).toEqual({
      from: '2026-10-05T00:00:00.000Z',
      to: '2026-11-04T00:00:00.000Z',
    })
  })

  it('reads custom dates on the owner’s clock, with the end day included', () => {
    const range = { preset: 'custom', from: '2026-11-01', to: '2026-11-02' } as const
    expect(rangeToIso(range, NOW, 0)).toEqual({
      from: '2026-11-01T00:00:00.000Z',
      to: '2026-11-03T00:00:00.000Z', // the whole of the 2nd
    })
    expect(rangeToIso(range, NOW, -180)).toEqual({
      from: '2026-11-01T03:00:00.000Z',
      to: '2026-11-03T03:00:00.000Z',
    })
  })

  it('accepts a custom range with only one end', () => {
    expect(rangeToIso({ preset: 'custom', from: '2026-11-01' }, NOW, 0)).toEqual({
      from: '2026-11-01T00:00:00.000Z',
    })
    expect(rangeToIso({ preset: 'custom', to: '2026-11-01' }, NOW, 0)).toEqual({
      to: '2026-11-02T00:00:00.000Z',
    })
  })

  it('accepts a single day', () => {
    expect(rangeToIso({ preset: 'custom', from: '2026-11-02', to: '2026-11-02' }, NOW, 0)).toEqual({
      from: '2026-11-02T00:00:00.000Z',
      to: '2026-11-03T00:00:00.000Z',
    })
  })

  it.each([
    [{ preset: 'custom' }],
    [{ preset: 'custom', from: '', to: '' }],
    [{ preset: 'custom', from: 'tomorrow' }],
    [{ preset: 'custom', from: '2026-02-31' }], // there is no 31 February
    [{ preset: 'custom', from: '2026-13-01' }],
    [{ preset: 'custom', from: '2026-11-05', to: '2026-11-02' }], // backwards
  ] as const)('refuses %j instead of asking the server something it will refuse', (range) => {
    expect(rangeToIso(range, NOW, 0)).toBeNull()
  })

  it('keeps working across a month and a year boundary', () => {
    expect(rangeToIso({ preset: '7' }, new Date('2027-01-03T12:00:00Z'), 0)).toEqual({
      from: '2026-12-28T00:00:00.000Z',
      to: '2027-01-04T00:00:00.000Z',
    })
  })
})

describe('browserOffsetMinutes', () => {
  it('is the opposite of JavaScript’s timezone offset (which counts the other way)', () => {
    const offset = new Date('2026-11-03T00:00:00Z').getTimezoneOffset()
    expect(browserOffsetMinutes(new Date('2026-11-03T00:00:00Z'))).toBe(-offset)
  })
})
