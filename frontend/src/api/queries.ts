// The cached server state. `status` is special: it is kept current by the live feed (a snapshot
// replaces it, events patch it), so it never refetches by itself. Everything else is a normal query
// that the live feed marks stale when something relevant happens.
import { useQuery, type QueryClient } from '@tanstack/react-query'
import { api, type ReportFilters } from './client'
import type {
  AccountType,
  BreakdownKind,
  ChainStatus,
  SignalStatus,
  Snapshot,
  TradeStatus,
} from './types'

export interface Paging {
  limit: number
  offset: number
}

export const keys = {
  status: ['status'] as const,
  risk: ['risk'] as const,
  groups: ['groups'] as const,
  group: (id: number) => ['groups', id] as const,
  chains: ['chains'] as const,
  trades: ['trades'] as const,
  signals: ['signals'] as const,
  riskEvents: ['risk-events'] as const,
  reports: ['reports'] as const,
  health: ['health'] as const,
  auth: ['auth'] as const,
  settings: ['settings'] as const,
  engine: ['engine'] as const,
  secrets: ['secrets'] as const,
}

export function useStatus() {
  return useQuery<Snapshot>({
    queryKey: keys.status,
    queryFn: ({ signal }) => api.status(signal),
    staleTime: Infinity, // the live feed keeps it current
  })
}

export function useEngine() {
  return useQuery({ queryKey: keys.engine, queryFn: ({ signal }) => api.engine.get(signal) })
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: ({ signal }) => api.settings.get(signal) })
}

export function useSecrets() {
  return useQuery({ queryKey: keys.secrets, queryFn: ({ signal }) => api.secrets.list(signal) })
}

export function useRisk() {
  return useQuery({ queryKey: keys.risk, queryFn: ({ signal }) => api.risk.get(signal) })
}

export function useGroups() {
  return useQuery({
    queryKey: keys.groups,
    queryFn: ({ signal }) => api.groups.list({ limit: 200 }, signal),
  })
}

export function useGroup(id: number) {
  return useQuery({
    queryKey: keys.group(id),
    queryFn: ({ signal }) => api.groups.get(id, signal),
  })
}

export interface TradeFilters extends Paging {
  group_id?: number
  status?: TradeStatus
  account_type?: AccountType
}

export function useTrades(filters: TradeFilters) {
  return useQuery({
    queryKey: [...keys.trades, filters],
    queryFn: ({ signal }) => api.trades.list(filters, signal),
    placeholderData: (previous) => previous, // keep the old page on screen while the next loads
  })
}

export interface SignalFilters extends Paging {
  group_id?: number
  status?: SignalStatus
}

export function useSignals(filters: SignalFilters) {
  return useQuery({
    queryKey: [...keys.signals, filters],
    queryFn: ({ signal }) => api.signals.list(filters, signal),
    placeholderData: (previous) => previous,
  })
}

export interface ChainFilters extends Paging {
  group_id?: number
  status?: ChainStatus
}

/** After a change the server confirmed, make the lists that show it fetch again. */
export function invalidateGroups(client: QueryClient): Promise<void> {
  return client.invalidateQueries({ queryKey: keys.groups })
}

// --- reports: nothing refreshes them by itself, the owner asks ("Refresh") or changes a filter ---

export function useReportSummary(filters: ReportFilters) {
  return useQuery({
    queryKey: [...keys.reports, 'summary', filters],
    queryFn: ({ signal }) => api.reports.summary(filters, signal),
    placeholderData: (previous) => previous,
  })
}

export function useReportBreakdown(by: BreakdownKind, filters: ReportFilters) {
  return useQuery({
    queryKey: [...keys.reports, 'breakdown', by, filters],
    queryFn: ({ signal }) => api.reports.breakdown(by, filters, signal),
    placeholderData: (previous) => previous,
  })
}

export function useReportEquity(filters: ReportFilters) {
  return useQuery({
    queryKey: [...keys.reports, 'equity', filters],
    queryFn: ({ signal }) => api.reports.equity(filters, signal),
    placeholderData: (previous) => previous,
  })
}

export function useReportDepth(filters: ReportFilters) {
  return useQuery({
    queryKey: [...keys.reports, 'depth', filters],
    queryFn: ({ signal }) => api.reports.depth(filters, signal),
    placeholderData: (previous) => previous,
  })
}

/** How often the page asks "is anything wrong?". Short enough to notice a drop within moments. */
export const HEALTH_POLL_MS = 15_000

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: HEALTH_POLL_MS,
    retry: false, // a failed check is itself the answer: "cannot reach the backend"
    staleTime: 0,
  })
}
