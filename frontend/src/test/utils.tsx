// Test helpers: a fake backend (`mockApi`) and a render function with the app's providers.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { keys } from '../api/queries'
import type { Snapshot } from '../api/types'
import { makeSnapshot } from './fixtures'

export interface Call {
  method: string
  path: string // including the query string, without /api/v1
  body: unknown
}

type Reply = Response | Error | ((call: Call) => Response | Error)
type Route = readonly [method: string, path: string | RegExp, reply: Reply]

export function json(body: unknown, status = 200): Response {
  return Response.json(body, { status })
}

export function apiError(status: number, code: string, message: string, details: unknown = null) {
  return json({ error: { code, message, details } }, status)
}

/**
 * Stands in for the backend. Routes are matched by method and path (the path without `/api/v1` and
 * without the query string, unless the route is a RegExp, which sees the whole thing). A request that
 * matches nothing fails the test, so a forgotten route is loud.
 */
export function mockApi(routes: readonly Route[]) {
  const calls: Call[] = []
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const full = url.replace(/^\/api\/v1/, '')
    const method = (init?.method ?? 'GET').toUpperCase()
    const call: Call = {
      method,
      path: full,
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined,
    }
    calls.push(call)
    const bare = full.split('?')[0] ?? full
    const route = routes.find(
      ([m, p]) => m === method && (typeof p === 'string' ? p === bare : p.test(full)),
    )
    if (route === undefined) {
      return Promise.reject(new Error(`unexpected request: ${method} ${full}`))
    }
    const reply = typeof route[2] === 'function' ? route[2](call) : route[2]
    return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply.clone())
  })
  vi.stubGlobal('fetch', fn)
  return {
    calls,
    /** Requests made so far with this method and path (query string ignored). */
    to: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path.split('?')[0] === path),
  }
}

export function testClient(status: Snapshot | null = makeSnapshot()): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  })
  if (status !== null) client.setQueryData(keys.status, status)
  return client
}

export function renderWith(
  ui: ReactElement,
  { route = '/', client = testClient() }: { route?: string; client?: QueryClient } = {},
) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}
