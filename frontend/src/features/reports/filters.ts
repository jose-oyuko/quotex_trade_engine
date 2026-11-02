import type { ReportFilters } from '../../api/client'
import { rangeToIso } from '../../lib/dates'
import type { ReportControls } from './FilterBar'

/** Turns the controls into what the API is asked, or says why it cannot be asked. */
export function toFilters(
  controls: ReportControls,
  now: Date,
  offsetMinutes: number,
): { filters: ReportFilters | null; error: string | null } {
  const range = rangeToIso(controls.range, now, offsetMinutes)
  if (range === null) {
    return {
      filters: null,
      error: 'Pick the dates the period starts and ends (the end cannot be before the start).',
    }
  }
  const filters: ReportFilters = {
    account_type: controls.account,
    utc_offset_minutes: offsetMinutes,
  }
  if (range.from !== undefined) filters.from = range.from
  if (range.to !== undefined) filters.to = range.to
  if (controls.groupId !== undefined) filters.group_id = controls.groupId
  if (controls.strategy !== undefined) filters.strategy = controls.strategy
  if (controls.asset !== '') filters.asset = controls.asset
  return { filters, error: null }
}
