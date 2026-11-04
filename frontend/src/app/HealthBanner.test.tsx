import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HEALTH_POLL_MS } from '../api/queries'
import type { Health } from '../api/types'
import { json, mockApi } from '../test/utils'
import { HealthBanner } from './HealthBanner'

function health(overrides: Partial<Health> = {}): Health {
  return {
    status: 'ok',
    problems: [],
    version: '0.1.0',
    environment: 'development',
    background_tasks: 2,
    database: 'ok',
    events_published: 0,
    writer: { queue_depth: 0, written: 0, failed: 0, dropped: 0, retrying: false },
    engine: { enabled: true, running: true, state: 'running', error: null },
    telegram: null,
    quotex: null,
    last_event_at: null,
    ws_clients: 0,
    ...overrides,
  }
}

function mount() {
  const client = new QueryClient()
  return render(
    <QueryClientProvider client={client}>
      <HealthBanner />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('HealthBanner', () => {
  it('draws nothing while everything is fine', async () => {
    const api = mockApi([['GET', '/health', json(health())]])
    const { container } = mount()
    await vi.waitFor(() => {
      expect(api.calls).toHaveLength(1)
    })
    expect(container).toBeEmptyDOMElement()
  })

  it('lists each problem the backend reports', async () => {
    mockApi([
      [
        'GET',
        '/health',
        json(
          health({
            status: 'degraded',
            problems: [
              'Quotex is not connected: no trade can be placed until it is.',
              'Telegram is not connected: signals are not being read.',
            ],
          }),
        ),
      ],
    ])
    mount()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Attention')
    expect(alert).toHaveTextContent('Quotex is not connected')
    expect(alert).toHaveTextContent('Telegram is not connected')
  })

  it('says so when the backend cannot be reached at all', async () => {
    mockApi([['GET', '/health', new Error('network down')]])
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the backend')
  })

  it('asks again by itself, so a problem appears and clears without a reload', async () => {
    let degraded = false
    const api = mockApi([
      [
        'GET',
        '/health',
        () =>
          json(
            health(
              degraded
                ? {
                    status: 'degraded',
                    problems: ['The database cannot be reached: nothing is being stored.'],
                  }
                : {},
            ),
          ),
      ],
    ])
    mount()
    await vi.waitFor(() => {
      expect(api.calls).toHaveLength(1)
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    degraded = true
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS + 100)
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('database cannot be reached')

    degraded = false
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_POLL_MS + 100)
    })
    await vi.waitFor(() => {
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
  })
})
