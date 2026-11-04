// The typed client for the REST API. One small `request` function does the HTTP, JSON and error
// handling; the `api` object below names every endpoint with its input and output types.
import type {
  Account,
  AuthState,
  AuthUser,
  AccountType,
  Chain,
  ChainControl,
  ChainDetail,
  ChainStatus,
  Controls,
  Group,
  GroupCreate,
  GroupRiskLimits,
  GroupRiskLimitsInput,
  GroupUpdate,
  Health,
  Page,
  ReportBreakdown,
  ReportDepth,
  ReportEquity,
  ReportSummary,
  BreakdownKind,
  Risk,
  RiskEvent,
  RiskLimits,
  RiskLimitsInput,
  Signal,
  SignalStatus,
  TelegramChat,
  Strategy,
  Snapshot,
  Trade,
  TradeStatus,
} from './types'

const BASE = '/api/v1'

/** The server answered with an error (`{"error": {"code", "message", "details"}}`). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

let unauthorizedHandler: (() => void) | null = null

/**
 * Called when the server says the session is gone (it expired, or the password was changed
 * elsewhere): the app then asks who is logged in and shows the login page. Returns a function that
 * removes the handler.
 */
export function onUnauthorized(handler: () => void): () => void {
  unauthorizedHandler = handler
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null
  }
}

/** Query parameters: an object whose values are text, numbers or booleans (null/undefined: left out). */
type Query = object

interface Options {
  query?: Query
  body?: unknown
  signal?: AbortSignal
}

function url(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {}) as [string, unknown][]) {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      params.set(key, String(value))
    }
  }
  const text = params.toString()
  return `${BASE}${path}${text ? `?${text}` : ''}`
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

async function errorFrom(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // not JSON (a proxy's error page, for instance): fall through to the generic message
  }
  const error = isRecord(body) ? body.error : undefined
  if (isRecord(error) && typeof error.code === 'string' && typeof error.message === 'string') {
    return new ApiError(response.status, error.code, error.message, error.details)
  }
  return new ApiError(
    response.status,
    'http_error',
    `The server answered HTTP ${String(response.status)}`,
  )
}

/** Throws `ApiError` for an error answer, and a plain `Error` if the server cannot be reached. */
export async function request<T>(method: string, path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body: string | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  let response: Response
  try {
    response = await fetch(url(path, options.query), {
      method,
      headers,
      body,
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('Cannot reach the backend. Is it running?', { cause: error })
  }
  if (!response.ok) {
    const error = await errorFrom(response)
    // A wrong password is also a 401, but with another code: only a lost session ends the visit.
    if (error.status === 401 && error.code === 'not_authenticated') unauthorizedHandler?.()
    throw error
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

interface ListFilters {
  limit?: number
  offset?: number
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>('GET', '/health', { signal }),
  status: (signal?: AbortSignal) => request<Snapshot>('GET', '/status', { signal }),

  groups: {
    list: (filters: ListFilters = {}, signal?: AbortSignal) =>
      request<Page<Group>>('GET', '/groups', { query: filters, signal }),
    get: (id: number, signal?: AbortSignal) =>
      request<Group>('GET', `/groups/${String(id)}`, { signal }),
    create: (body: GroupCreate) => request<Group>('POST', '/groups', { body }),
    update: (id: number, body: GroupUpdate) =>
      request<Group>('PUT', `/groups/${String(id)}`, { body }),
    remove: (id: number) => request<undefined>('DELETE', `/groups/${String(id)}`),
    pause: (id: number) => request<Group>('POST', `/groups/${String(id)}/pause`),
    resume: (id: number) => request<Group>('POST', `/groups/${String(id)}/resume`),
    risk: (id: number, signal?: AbortSignal) =>
      request<GroupRiskLimits>('GET', `/groups/${String(id)}/risk`, { signal }),
    setRisk: (id: number, body: GroupRiskLimitsInput) =>
      request<GroupRiskLimits>('PUT', `/groups/${String(id)}/risk`, { body }),
  },

  auth: {
    state: (signal?: AbortSignal) => request<AuthState>('GET', '/auth/state', { signal }),
    setup: (body: { setup_code: string; username: string; password: string }) =>
      request<AuthUser>('POST', '/auth/setup', { body }),
    login: (body: { username: string; password: string }) =>
      request<AuthUser>('POST', '/auth/login', { body }),
    logout: () => request<undefined>('POST', '/auth/logout'),
    changePassword: (body: { current_password: string; new_password: string }) =>
      request<undefined>('POST', '/auth/password', { body }),
  },

  telegram: {
    chats: (signal?: AbortSignal) =>
      request<{ items: TelegramChat[] }>('GET', '/telegram/chats', { signal }),
  },

  chains: {
    list: (
      filters: ListFilters & {
        group_id?: number
        status?: ChainStatus
        account_type?: AccountType
      } = {},
      signal?: AbortSignal,
    ) => request<Page<Chain>>('GET', '/chains', { query: filters, signal }),
    get: (id: string, signal?: AbortSignal) =>
      request<ChainDetail>('GET', `/chains/${id}`, { signal }),
    stopAfterCurrent: (id: string) =>
      request<ChainControl>('POST', `/chains/${id}/stop-after-current`),
    end: (id: string) => request<ChainControl>('POST', `/chains/${id}/end`),
  },

  trades: {
    list: (
      filters: ListFilters & {
        group_id?: number
        status?: TradeStatus
        account_type?: AccountType
      } = {},
      signal?: AbortSignal,
    ) => request<Page<Trade>>('GET', '/trades', { query: filters, signal }),
    get: (id: string, signal?: AbortSignal) => request<Trade>('GET', `/trades/${id}`, { signal }),
  },

  signals: {
    list: (
      filters: ListFilters & { group_id?: number; status?: SignalStatus } = {},
      signal?: AbortSignal,
    ) => request<Page<Signal>>('GET', '/signals', { query: filters, signal }),
    get: (id: string, signal?: AbortSignal) => request<Signal>('GET', `/signals/${id}`, { signal }),
  },

  risk: {
    get: (signal?: AbortSignal) => request<Risk>('GET', '/risk', { signal }),
    setLimits: (body: RiskLimitsInput) => request<RiskLimits>('PUT', '/risk/limits', { body }),
    events: (filters: ListFilters = {}, signal?: AbortSignal) =>
      request<Page<RiskEvent>>('GET', '/risk/events', { query: filters, signal }),
  },

  killSwitch: {
    engage: (stopChains = false) =>
      request<Controls>('POST', '/kill-switch', { body: { stop_chains: stopChains } }),
    release: () => request<Controls>('DELETE', '/kill-switch'),
  },

  account: {
    get: (signal?: AbortSignal) => request<Account>('GET', '/account', { signal }),
    set: (accountType: AccountType) =>
      request<Account>('PUT', '/account', { body: { account_type: accountType } }),
  },

  reports: {
    summary: (filters: ReportFilters, signal?: AbortSignal) =>
      request<ReportSummary>('GET', '/reports/summary', { query: reportQuery(filters), signal }),
    breakdown: (by: BreakdownKind, filters: ReportFilters, signal?: AbortSignal) =>
      request<ReportBreakdown>('GET', '/reports/breakdown', {
        query: { ...reportQuery(filters), by },
        signal,
      }),
    equity: (filters: ReportFilters, signal?: AbortSignal) =>
      request<ReportEquity>('GET', '/reports/equity', { query: reportQuery(filters), signal }),
    depth: (filters: ReportFilters, signal?: AbortSignal) =>
      request<ReportDepth>('GET', '/reports/depth', { query: reportQuery(filters), signal }),
  },
}

/** What every report can be narrowed by. `from` is inclusive, `to` exclusive (ISO times). */
export interface ReportFilters {
  account_type: AccountType
  from?: string
  to?: string
  group_id?: number
  strategy?: Strategy
  asset?: string
  utc_offset_minutes?: number
}

function reportQuery(filters: ReportFilters): Query {
  return { ...filters }
}

/** Address of a CSV download (a plain link: the browser saves the file). */
export function reportCsvUrl(
  kind: 'trades' | BreakdownKind,
  filters: ReportFilters,
  delimiter: 'comma' | 'semicolon' = 'comma',
): string {
  const query = kind === 'trades' ? reportQuery(filters) : { ...reportQuery(filters), by: kind }
  const path = kind === 'trades' ? '/reports/export/trades.csv' : '/reports/export/breakdown.csv'
  return url(path, { ...query, delimiter })
}
