import type { QuotexLoginStatus } from '../../api/types'

/** A Quotex login answer for tests; `over` replaces fields. By default: logged out and ready. */
export function quotexStatus(over: Partial<QuotexLoginStatus> = {}): QuotexLoginStatus {
  return {
    state: 'logged_out',
    configured: true,
    pin_prompt: null,
    message: null,
    engine_running: false,
    ...over,
  }
}
