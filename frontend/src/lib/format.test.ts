import { describe, expect, it } from 'vitest'
import {
  formatCountdown,
  formatMoney,
  formatMs,
  formatTime,
  median,
  moneySign,
  titleCase,
} from './format'

describe('formatMoney', () => {
  it.each([
    ['1', '1'],
    ['1.50', '1.50'],
    ['1234.5', '1,234.5'],
    ['1234567.891', '1,234,567.891'],
    ['-0.85', '-0.85'],
    ['-12345.60', '-12,345.60'],
    ['+3', '+3'],
  ])('shows %s as %s, keeping every decimal', (input, expected) => {
    expect(formatMoney(input)).toBe(expected)
  })

  it('shows a dash for nothing, and leaves odd text alone rather than guessing', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney('')).toBe('—')
    expect(formatMoney('abc')).toBe('abc')
  })

  it('never goes through a float: a long amount keeps all its digits', () => {
    expect(formatMoney('12345678901234567890.12345678')).toBe('12,345,678,901,234,567,890.12345678')
  })
})

describe('moneySign', () => {
  it.each([
    ['0.85', 'profit'],
    ['-0.85', 'loss'],
    ['0', 'flat'],
    ['0.00', 'flat'],
    ['-0.00', 'flat'],
    [null, 'flat'],
  ] as const)('%s is %s', (input, expected) => {
    expect(moneySign(input)).toBe(expected)
  })
})

describe('other formats', () => {
  it('formats milliseconds with a sensible precision', () => {
    expect(formatMs(0.1234)).toBe('0.12 ms')
    expect(formatMs(12.34)).toBe('12.3 ms')
    expect(formatMs(1250)).toBe('1,250 ms')
    expect(formatMs(null)).toBe('—')
  })

  it('formats a countdown and never goes below zero', () => {
    expect(formatCountdown(75)).toBe('1:15')
    expect(formatCountdown(5.9)).toBe('0:05')
    expect(formatCountdown(-3)).toBe('0:00')
  })

  it('computes a median', () => {
    expect(median([])).toBeNull()
    expect(median([5])).toBe(5)
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 3, 2])).toBe(2.5)
  })

  it('handles missing or broken times', () => {
    expect(formatTime(null)).toBe('—')
    expect(formatTime('not a date')).toBe('—')
    expect(formatTime('2026-11-02T10:00:00Z')).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })

  it('turns identifiers into words', () => {
    expect(titleCase('flip_every_loss')).toBe('Flip every loss')
  })
})
