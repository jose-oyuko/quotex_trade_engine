// What Deriv offers, for the session form (Phase 21): its assets grouped by market, and the trade
// lengths each allows, in the same words the backend uses when it skips a round.
import type { DerivAsset } from '../../api/types'

const MARKETS: { market: string; label: string }[] = [
  { market: 'forex', label: 'Forex pairs' },
  { market: 'synthetic_index', label: 'Synthetic indices' },
]

export interface AssetGroup {
  label: string
  assets: DerivAsset[]
}

/** Forex pairs first, then synthetic indices, then anything else Deriv lists; by name in each. */
export function groupAssets(assets: DerivAsset[]): AssetGroup[] {
  const byName = (a: DerivAsset, b: DerivAsset) => a.name.localeCompare(b.name)
  const known = new Set(MARKETS.map((m) => m.market))
  const groups = MARKETS.map(({ market, label }) => ({
    label,
    assets: assets.filter((a) => a.market === market).sort(byName),
  }))
  groups.push({
    label: 'Other markets',
    assets: assets.filter((a) => !known.has(a.market)).sort(byName),
  })
  return groups.filter((g) => g.assets.length > 0)
}

/** `60` -> "1 min", `86400` -> "1 day" (as the backend writes it). */
export function humanLength(seconds: number): string {
  for (const [size, unit] of [
    [86_400, 'day'],
    [3600, 'hour'],
    [60, 'min'],
  ] as const) {
    if (seconds % size === 0) {
      const count = seconds / size
      return unit === 'min'
        ? `${String(count)} min`
        : `${String(count)} ${unit}${count === 1 ? '' : 's'}`
    }
  }
  return `${String(seconds)} s`
}

export function describeLengths(asset: DerivAsset): string {
  const ranges = asset.lengths ?? []
  if (ranges.length === 0) return 'none (Rise/Fall is not offered on it)'
  return ranges.map((r) => `${humanLength(r.min_s)} to ${humanLength(r.max_s)}`).join(', ')
}

/** Does Deriv offer this trade length on the asset? null while its lengths are not known yet. */
export function offers(asset: DerivAsset, durationS: number): boolean | null {
  if (asset.lengths === null) return null
  return asset.lengths.some((r) => r.min_s <= durationS && durationS <= r.max_s)
}

/** The warning under the trade length when Deriv would refuse it; null when it would not. */
export function lengthWarning(asset: DerivAsset | undefined, durationS: number): string | null {
  if (asset === undefined || offers(asset, durationS) !== false) return null
  return (
    `Deriv does not offer ${humanLength(durationS)} Rise/Fall on ${asset.asset}: it offers ` +
    `${describeLengths(asset)}. Every round would be skipped.`
  )
}
