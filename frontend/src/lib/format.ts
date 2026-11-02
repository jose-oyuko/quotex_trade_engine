// Display helpers. Money arrives as text ("1234.50") and is only ever handled as text here, never
// converted to a float, so what the screen shows is exactly what the server said.

/** `1234.5` -> `1,234.5`; keeps the sign and every decimal. `null` shows as a dash. */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value)
  if (match === null) return value
  const [, sign = '', whole = '', fraction = ''] = match
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction}`
}

/** `'profit'`, `'loss'` or `'flat'`, from the text of a signed amount. */
export function moneySign(value: string | null | undefined): 'profit' | 'loss' | 'flat' {
  if (value === null || value === undefined) return 'flat'
  if (value.startsWith('-')) return /[1-9]/.test(value) ? 'loss' : 'flat'
  return /[1-9]/.test(value) ? 'profit' : 'flat'
}

const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : timeFormat.format(date)
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : dateTimeFormat.format(date)
}

/** Milliseconds with a sensible number of digits: `0.14 ms`, `12 ms`, `1,250 ms`. */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value < 1) return `${value.toFixed(2)} ms`
  if (value < 100) return `${value.toFixed(1)} ms`
  return `${Math.round(value).toLocaleString('en-US')} ms`
}

/** Seconds as `m:ss`. */
export function formatCountdown(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(whole / 60))}:${String(whole % 60).padStart(2, '0')}`
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  const upper = sorted[middle] ?? 0
  const lower = sorted[middle - 1] ?? upper
  return sorted.length % 2 === 1 ? upper : (lower + upper) / 2
}

export function titleCase(value: string): string {
  return value.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase())
}
