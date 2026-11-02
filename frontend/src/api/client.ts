// The typed client for the REST API. One small `request` function does the HTTP, JSON and error
// handling; the `api` object below names every endpoint with its input and output types.
import type {
  Account,
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
  Risk,
  RiskEvent,
  RiskLimits,
  RiskLimitsInput,
  Signal,
  SignalStatus,
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
  if (!response.ok) throw await errorFrom(response)
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
}
