import type { TelegramLoginStatus } from '../../api/types'

/** A Telegram login answer for tests; `over` replaces fields. By default: logged out and ready. */
export function telegramStatus(over: Partial<TelegramLoginStatus> = {}): TelegramLoginStatus {
  return {
    state: 'logged_out',
    configured: true,
    phone_hint: null,
    delivery: null,
    resends_left: 0,
    problem: null,
    engine_running: false,
    ...over,
  }
}
