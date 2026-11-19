// Deriv's assets under the names people know ("Volatility 75 (1s) Index") instead of their codes
// (`1HZ75V`). The names come from Deriv's own list (`GET /prices/assets`); these few are known
// without it, so the page still reads well when Deriv cannot be reached.
import type { AssetName } from '../../api/types'

export const KNOWN_ASSETS: AssetName[] = [
  { asset: '1HZ10V', name: 'Volatility 10 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ15V', name: 'Volatility 15 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ25V', name: 'Volatility 25 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ30V', name: 'Volatility 30 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ50V', name: 'Volatility 50 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ75V', name: 'Volatility 75 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ90V', name: 'Volatility 90 (1s) Index', group: 'Volatility indices' },
  { asset: '1HZ100V', name: 'Volatility 100 (1s) Index', group: 'Volatility indices' },
  { asset: 'R_10', name: 'Volatility 10 Index', group: 'Volatility indices' },
  { asset: 'R_25', name: 'Volatility 25 Index', group: 'Volatility indices' },
  { asset: 'R_50', name: 'Volatility 50 Index', group: 'Volatility indices' },
  { asset: 'R_75', name: 'Volatility 75 Index', group: 'Volatility indices' },
  { asset: 'R_100', name: 'Volatility 100 Index', group: 'Volatility indices' },
  { asset: 'EURUSD', name: 'EUR/USD', group: 'Forex' },
]

/** "Volatility 75 (1s) Index (1HZ75V)", or the code alone when its name is not known. */
export function assetLabel(asset: string, names: readonly AssetName[]): string {
  const found = names.find((n) => n.asset === asset) ?? KNOWN_ASSETS.find((n) => n.asset === asset)
  return found ? `${found.name} (${asset})` : asset
}

/** The assets by family, in Deriv's order, for a picker. */
export function groupedAssets(names: readonly AssetName[]): [string, AssetName[]][] {
  const groups = new Map<string, AssetName[]>()
  for (const n of names.length > 0 ? names : KNOWN_ASSETS) {
    const list = groups.get(n.group) ?? []
    list.push(n)
    groups.set(n.group, list)
  }
  // the volatility indices first: they are the ones traded in sessions
  return [...groups.entries()].sort(([a], [b]) =>
    a === 'Volatility indices' ? -1 : b === 'Volatility indices' ? 1 : a.localeCompare(b),
  )
}
