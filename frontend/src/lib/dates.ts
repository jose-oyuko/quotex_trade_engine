// Date ranges for the reports: "the last 7 days" means calendar days on the owner's clock, so
// the boundaries are local midnights, sent to the server as UTC instants.

export type RangePreset = 'all' | 'today' | '7' | '30' | 'custom'

export interface DateRange {
  preset: RangePreset
  /** `YYYY-MM-DD`, only for `custom`. */
  from?: string
  /** `YYYY-MM-DD`, inclusive, only for `custom`. */
  to?: string
}

export interface IsoRange {
  from?: string
  to?: string
}

const MINUTE = 60_000
const DAY = 24 * 60 * MINUTE

/** The browser's own offset from UTC in minutes (UTC-3 is -180). */
export function browserOffsetMinutes(now: Date = new Date()): number {
  return -now.getTimezoneOffset()
}

function parseDay(day: string | undefined): { y: number; m: number; d: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '')
  if (match === null) return null
  const [, y = '', m = '', d = ''] = match
  const parts = { y: Number(y), m: Number(m), d: Number(d) }
  const check = new Date(Date.UTC(parts.y, parts.m - 1, parts.d))
  // reject 2026-02-31 and the like: JavaScript rolls them over into the next month
  return check.getUTCFullYear() === parts.y && check.getUTCMonth() === parts.m - 1 ? parts : null
}

/** The instant a calendar day begins on a clock `offsetMinutes` ahead of UTC. */
function dayStart(y: number, m: number, d: number, offsetMinutes: number): number {
  return Date.UTC(y, m - 1, d) - offsetMinutes * MINUTE
}

/**
 * The UTC instants a range starts (inclusive) and ends (exclusive), as ISO strings. `custom` with
 * an unreadable or backwards range yields `null`, so the page can say so instead of asking the
 * server something it will refuse.
 */
export function rangeToIso(range: DateRange, now: Date, offsetMinutes: number): IsoRange | null {
  const localNow = new Date(now.getTime() + offsetMinutes * MINUTE)
  const todayStart = dayStart(
    localNow.getUTCFullYear(),
    localNow.getUTCMonth() + 1,
    localNow.getUTCDate(),
    offsetMinutes,
  )
  switch (range.preset) {
    case 'all':
      return {}
    case 'today':
      return {
        from: new Date(todayStart).toISOString(),
        to: new Date(todayStart + DAY).toISOString(),
      }
    case '7':
    case '30': {
      const days = Number(range.preset)
      return {
        from: new Date(todayStart - (days - 1) * DAY).toISOString(),
        to: new Date(todayStart + DAY).toISOString(),
      }
    }
    case 'custom': {
      const start = parseDay(range.from)
      const end = parseDay(range.to)
      if (start === null && end === null) return null
      const out: IsoRange = {}
      if (start !== null)
        out.from = new Date(dayStart(start.y, start.m, start.d, offsetMinutes)).toISOString()
      if (end !== null)
        out.to = new Date(dayStart(end.y, end.m, end.d, offsetMinutes) + DAY).toISOString()
      if (out.from !== undefined && out.to !== undefined && out.from >= out.to) return null
      return out
    }
  }
}
