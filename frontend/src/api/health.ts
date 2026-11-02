import type { Health } from './types'

export type { Health }

function isHealth(value: unknown): value is Health {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    v.status === 'ok' &&
    typeof v.version === 'string' &&
    typeof v.environment === 'string' &&
    typeof v.background_tasks === 'number' &&
    typeof v.engine === 'object' &&
    v.engine !== null
  )
}

/** Calls GET /api/v1/health. Throws on network errors, non-2xx answers or an unexpected body. */
export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch('/api/v1/health', { signal })
  if (!response.ok) throw new Error(`Backend answered HTTP ${String(response.status)}`)
  const body: unknown = await response.json()
  if (!isHealth(body)) throw new Error('Unexpected health response')
  return body
}
