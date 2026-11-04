import type { EngineInfo } from '../../api/types'

/** An engine answer for tests; `over` replaces fields. By default: stopped, every login present. */
export function engineInfo(over: Partial<EngineInfo> = {}): EngineInfo {
  return {
    state: 'stopped',
    desired: false,
    error: null,
    since: null,
    real_trading_allowed: false,
    logins: [
      { label: 'Quotex email', present: true, source: 'dashboard', required: true },
      { label: 'Quotex password', present: true, source: 'dashboard', required: true },
      { label: 'Telegram API hash', present: true, source: 'dashboard', required: true },
      { label: 'Telegram API id', present: true, source: 'dashboard', required: true },
    ],
    missing_logins: [],
    ...over,
  }
}
