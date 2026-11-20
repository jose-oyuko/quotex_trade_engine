// The Market page's rules (decision D-85): timeframes, the chunks of candles the chart loads, the
// scan form (mirroring backend/app/api/schemas/market.py; the server checks everything again) and
// the statistics in words. Times are UTC throughout, like the chart.
import type {
  MarketRules,
  MarketStats,
  Pattern,
  Rate,
  Scan,
  ScanInput,
  Trend,
} from '../../api/types'

export const TIMEFRAMES = [
  { value: 60, label: 'M1' },
  { value: 300, label: 'M5' },
  { value: 900, label: 'M15' },
  { value: 1800, label: 'M30' },
  { value: 3600, label: 'H1' },
] as const

/** Candles per request; the server allows 5,000. */
export const CHUNK = 1000
export const MAX_SCAN_DAYS = 31

export const PATTERN_TEXT: Record<Pattern, string> = {
  alternating: 'Alternating: every candle the other colour (yours)',
  mixed: 'Mixed: alternating, with a few candles allowed not to',
  tight: 'Tight: a narrow range compared with the average candle',
  overlap: 'Overlap: each candle inside the one before',
  choppy: 'Choppy: much movement, little net progress',
}

export const PATTERNS = Object.keys(PATTERN_TEXT) as Pattern[]

/** "M5", or "90 s" for a length that has no name. */
export function lengthLabel(length: number): string {
  return TIMEFRAMES.find((t) => t.value === length)?.label ?? `${String(length)} s`
}

/** The chunk (of `CHUNK` candles) holding a moment, and the period a chunk covers. */
export function chunkOf(epoch: number, length: number): number {
  return Math.floor(epoch / (CHUNK * length))
}

export function chunkSpan(chunk: number, length: number): [number, number] {
  return [chunk * CHUNK * length, (chunk + 1) * CHUNK * length]
}

/** The chunks covering a period, with one more on each side so scrolling finds candles ready. */
export function chunksAround(from: number, to: number, length: number): number[] {
  const first = chunkOf(from, length) - 1
  const last = chunkOf(to, length) + 1
  return Array.from({ length: last - first + 1 }, (_, i) => first + i)
}

export const epochOf = (iso: string) => Math.floor(Date.parse(iso) / 1000)
export const isoOf = (epoch: number) => new Date(epoch * 1000).toISOString().replace('.000Z', 'Z')

/** `YYYY-MM-DDTHH:MM` in UTC, for a `datetime-local` field. */
export function inputOf(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(0, 16)
}

/** A `datetime-local` value read as UTC; null when empty or not a time. */
export function epochOfInput(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return null
  const parsed = Date.parse(`${value.slice(0, 16)}:00Z`)
  return Number.isNaN(parsed) ? null : parsed / 1000
}

export interface ScanFormValues {
  start: string
  end: string
  pattern: Pattern
  candles: string
  misses: string
  width: string
  net_share: string
  breakout_candles: string
  breakout_by: 'close' | 'touch'
}

export type ScanErrors = Partial<Record<keyof ScanFormValues, string>>

/** The owner's definition: 5 alternating candles, a breakout of 2 closes (the server's default). */
export const DEFAULT_RULES: MarketRules = {
  pattern: 'alternating',
  candles: 5,
  misses: 1,
  width: 2,
  net_share: 0.2,
  breakout_candles: 2,
  breakout_by: 'close',
}

export function rulesToForm(rules: MarketRules): Omit<ScanFormValues, 'start' | 'end'> {
  return {
    pattern: rules.pattern,
    candles: String(rules.candles),
    misses: String(rules.misses),
    width: String(rules.width),
    net_share: String(rules.net_share),
    breakout_candles: String(rules.breakout_candles),
    breakout_by: rules.breakout_by,
  }
}

export function emptyScan(last: number | null): ScanFormValues {
  const end = last === null ? Math.floor(Date.now() / 1000) : last
  const rounded = Math.ceil(end / 60) * 60
  return {
    start: inputOf(rounded - 86_400),
    end: inputOf(rounded),
    ...rulesToForm(DEFAULT_RULES),
  }
}

const whole = (text: string) => (/^\d+$/.test(text.trim()) ? Number(text) : Number.NaN)
const decimal = (text: string) => (text.trim() === '' ? Number.NaN : Number(text))

export function validateScan(values: ScanFormValues): ScanErrors {
  const errors: ScanErrors = {}
  const start = epochOfInput(values.start)
  const end = epochOfInput(values.end)
  if (start === null) errors.start = 'Choose when the period starts'
  if (end === null) errors.end = 'Choose when the period ends'
  if (start !== null && end !== null) {
    if (end <= start) errors.end = 'The end must come after the start'
    else if (end - start > MAX_SCAN_DAYS * 86_400)
      errors.end = `At most ${String(MAX_SCAN_DAYS)} days`
  }
  const candles = whole(values.candles)
  if (!(candles >= 2 && candles <= 50)) errors.candles = 'From 2 to 50 candles'
  if (values.pattern === 'mixed') {
    const misses = whole(values.misses)
    const most = Number.isNaN(candles) ? 48 : Math.max(candles - 2, 0)
    if (!(misses >= 0 && misses <= most)) errors.misses = `From 0 to ${String(most)}`
  }
  if (values.pattern === 'tight') {
    const width = decimal(values.width)
    if (!(width > 0 && width <= 20)) errors.width = 'Above 0, at most 20'
  }
  if (values.pattern === 'choppy') {
    const share = decimal(values.net_share)
    if (!(share > 0 && share < 1)) errors.net_share = 'Between 0 and 1, like 0.2'
  }
  const breakout = whole(values.breakout_candles)
  if (!(breakout >= 1 && breakout <= 10)) errors.breakout_candles = 'From 1 to 10 candles'
  return errors
}

export function toScanInput(asset: string, length: number, values: ScanFormValues): ScanInput {
  return {
    asset,
    length,
    deep: 6,
    start: isoOf(epochOfInput(values.start) ?? 0),
    end: isoOf(epochOfInput(values.end) ?? 0),
    rules: {
      pattern: values.pattern,
      candles: Number(values.candles),
      misses: Number(values.misses),
      width: Number(values.width),
      net_share: Number(values.net_share),
      breakout_candles: Number(values.breakout_candles),
      breakout_by: values.breakout_by,
    },
  }
}

const pct = (share: number) => `${(share * 100).toFixed(1)}%`
const range = (rate: Rate) => `${pct(rate.low)} to ${pct(rate.high)}`

/** "12 candles (12 min)" */
export function candlesText(count: number, length: number): string {
  const minutes = (count * length) / 60
  const time = minutes >= 120 ? `${(minutes / 60).toFixed(1)} h` : `${minutes.toFixed(0)} min`
  return `${count.toLocaleString('en-US', { maximumFractionDigits: 1 })} candles (${time})`
}

/** Whether two shares differ by more than noise: their 95% ranges do not overlap. */
export function differs(a: Rate, b: Rate): boolean {
  return a.total > 0 && b.total > 0 && (a.high < b.low || b.high < a.low)
}

/** The statistics of a scan as sentences. */
export function statsText(stats: MarketStats, length: number): string[] {
  const lines = [
    `${String(stats.consolidations)} consolidations (${String(stats.breakouts)} broke out); ` +
      `${pct(stats.in_consolidation)} of the time was inside one.`,
  ]
  if (stats.trend_wait.count > 0) {
    lines.push(
      `After a breakout the next consolidation was found after a median ` +
        `${candlesText(stats.trend_wait.median, length)}; from any moment, after ` +
        `${candlesText(stats.any_wait.median, length)}.`,
    )
  }
  if (stats.first_with.total > 0) {
    lines.push(
      `The candle after a breakout went the breakout's way ${pct(stats.first_with.share)} of the ` +
        `time (likely ${range(stats.first_with)}); breaking even at 88% needs ` +
        `${pct(stats.break_even)}.`,
    )
  }
  lines.push(
    `Flip pairs that lost ${String(stats.deep)} trades or more in a row: ` +
      `${pct(stats.deep_trend.share)} of those started while trending, ` +
      `${pct(stats.deep_any.share)} of those started at any moment` +
      (differs(stats.deep_trend, stats.deep_any)
        ? '.'
        : ': no real difference (within the 95% ranges).'),
  )
  if (stats.described.total > 0) {
    lines.push(
      `${pct(stats.described.share)} of the candles of the stretches that took pairs that deep ` +
        `lie inside a consolidation.`,
    )
  }
  return lines
}

/** The trend that followed each consolidation's breakout, if any. */
export function trendAfter(scan: Scan): Map<number, Trend> {
  const byStart = new Map(scan.trends.map((t) => [epochOf(t.start), t]))
  const found = new Map<number, Trend>()
  scan.consolidations.forEach((c, i) => {
    const trend = c.breakout ? byStart.get(epochOf(c.breakout.known)) : undefined
    if (trend) found.set(i, trend)
  })
  return found
}
