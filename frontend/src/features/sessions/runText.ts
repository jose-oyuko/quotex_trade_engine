// The words for a session's schedule and for how its runs end.
import type { RunEndReason, Session, SessionRun } from '../../api/types'
import { WEEKDAYS } from './sessionSchema'

export const END_REASONS: Record<RunEndReason, string> = {
  window_ended: 'The window ended',
  profit_target: 'Profit target reached',
  loss_limit: 'Loss limit reached',
  max_pairs: 'The maximum number of pairs was opened',
  stopped: 'Stopped by you',
  kill_switch: 'The kill switch was engaged',
  engine_stopped: 'The engine was stopped',
  interrupted: 'The application stopped while it ran',
  error: 'An error stopped it',
}

export function runStateText(run: SessionRun): string {
  if (run.state === 'running') return 'Running'
  if (run.state === 'stopping') return 'Stopping: no new pairs, running chains finish'
  return run.end_reason === null ? 'Ended' : END_REASONS[run.end_reason]
}

/** "Every day", "Mon–Fri", "Mon, Wed" or "Once". */
export function repeatText(session: Pick<Session, 'repeat' | 'weekdays'>): string {
  if (session.repeat === 'once') return 'Once'
  const days = [...session.weekdays].sort((a, b) => a - b)
  if (days.length === 7) return 'Every day'
  if (days.length === 5 && days.every((d, i) => d === i)) return 'Mon–Fri'
  return days.map((d) => WEEKDAYS[d]?.label ?? String(d)).join(', ')
}

export function spacingText(session: Pick<Session, 'mode' | 'max_open_pairs' | 'pause_s'>): string {
  if (session.mode === 'every_candle') {
    return `A pair every candle, up to ${String(session.max_open_pairs)} open`
  }
  return session.pause_s > 0
    ? `One pair at a time, ${String(session.pause_s)} s pause`
    : 'One pair at a time'
}
