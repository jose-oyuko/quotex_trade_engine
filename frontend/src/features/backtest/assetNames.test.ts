import { describe, expect, it } from 'vitest'
import { assetLabel, groupedAssets } from './assetNames'

const deriv = [
  { asset: 'BOOM500', name: 'Boom 500 Index', group: 'Crash and Boom' },
  { asset: 'R_10', name: 'Volatility 10 Index', group: 'Volatility indices' },
  { asset: 'EURUSD', name: 'EUR/USD', group: 'Forex' },
]

describe('asset names', () => {
  it('puts the code behind the name people know', () => {
    expect(assetLabel('R_10', deriv)).toBe('Volatility 10 Index (R_10)')
    expect(assetLabel('NEW1', deriv)).toBe('NEW1')
  })

  it('knows the volatility indices even without Deriv’s list', () => {
    expect(assetLabel('1HZ75V', [])).toBe('Volatility 75 (1s) Index (1HZ75V)')
    expect(assetLabel('R_75', [])).toBe('Volatility 75 Index (R_75)')
  })

  it('groups the picker by family, the volatility indices first', () => {
    expect(groupedAssets(deriv).map(([group]) => group)).toEqual([
      'Volatility indices',
      'Crash and Boom',
      'Forex',
    ])
    const offline = groupedAssets([])
    expect(offline[0]?.[0]).toBe('Volatility indices')
    expect(offline[0]?.[1].map((a) => a.asset)).toContain('1HZ75V')
  })
})
