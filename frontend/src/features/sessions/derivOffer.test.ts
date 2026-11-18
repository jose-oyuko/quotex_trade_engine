import { describe, expect, it } from 'vitest'
import type { DerivAsset } from '../../api/types'
import { assetProblemFor } from './sessionSchema'
import { describeLengths, groupAssets, humanLength, lengthWarning, offers } from './derivOffer'

const asset = (overrides: Partial<DerivAsset>): DerivAsset => ({
  asset: 'EURUSD',
  name: 'EUR/USD',
  market: 'forex',
  is_open: true,
  lengths: [{ min_s: 900, max_s: 31_536_000 }],
  ...overrides,
})

describe('what Deriv offers', () => {
  it('writes trade lengths as the backend does', () => {
    expect([15, 60, 900, 3600, 7200, 86_400, 31_536_000].map(humanLength)).toEqual([
      '15 s',
      '1 min',
      '15 min',
      '1 hour',
      '2 hours',
      '1 day',
      '365 days',
    ])
    expect(describeLengths(asset({}))).toBe('15 min to 365 days')
    expect(describeLengths(asset({ lengths: [] }))).toBe('none (Rise/Fall is not offered on it)')
  })

  it('knows a length is offered, refused, or not known yet', () => {
    expect(offers(asset({}), 900)).toBe(true)
    expect(offers(asset({}), 60)).toBe(false)
    expect(offers(asset({ lengths: null }), 60)).toBeNull()
    expect(lengthWarning(asset({}), 60)).toBe(
      'Deriv does not offer 1 min Rise/Fall on EURUSD: it offers 15 min to 365 days. Every round would be skipped.',
    )
    expect(lengthWarning(asset({ lengths: null }), 60)).toBeNull()
    expect(lengthWarning(undefined, 60)).toBeNull()
  })

  it('groups forex pairs first, then synthetic indices, then the rest, by name', () => {
    const groups = groupAssets([
      asset({ asset: 'R_75', name: 'Volatility 75 Index', market: 'synthetic_index' }),
      asset({ asset: 'GBPUSD', name: 'GBP/USD' }),
      asset({ asset: 'cryBTCUSD', name: 'BTC/USD', market: 'cryptocurrency' }),
      asset({}),
    ])
    expect(groups.map((g) => [g.label, g.assets.map((a) => a.asset)])).toEqual([
      ['Forex pairs', ['EURUSD', 'GBPUSD']],
      ['Synthetic indices', ['R_75']],
      ['Other markets', ['cryBTCUSD']],
    ])
  })
})

describe('the asset name, by broker', () => {
  it('follows Quotex’s names on Quotex and Deriv’s on Deriv', () => {
    expect(assetProblemFor('quotex', 'EURUSD_otc')).toBeNull()
    expect(assetProblemFor('quotex', 'R_75')).toMatch(/Quotex name/)
    expect(assetProblemFor('deriv', 'R_75')).toBeNull()
    expect(assetProblemFor('deriv', '1HZ100V')).toBeNull()
    expect(assetProblemFor('deriv', 'EURUSD_otc')).toMatch(/Deriv has no OTC pairs/)
    expect(assetProblemFor('deriv', 'EUR/USD')).toMatch(/Deriv's name/)
  })
})
