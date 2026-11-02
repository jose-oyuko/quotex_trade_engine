import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../api/queries'
import type { Snapshot } from '../api/types'
import { LiveStatusContext } from '../live/liveStatus'
import {
  makeBreakdown,
  makeDepth,
  makeEquity,
  makeGroup,
  makeSnapshot,
  makeSummary,
  page,
} from '../test/fixtures'
import { json, mockApi } from '../test/utils'
import { ErrorBoundary } from './ErrorBoundary'
import { routes } from './router'

afterEach(() => {
  vi.unstubAllGlobals()
})

const risk = json({
  controls: makeSnapshot().controls,
  day: null,
  open_trades: 0,
  open_exposure: '0',
})
const HEALTHY = {
  status: 'ok',
  problems: [],
  version: '0.1.0',
  environment: 'development',
  background_tasks: 0,
  database: 'ok',
  events_published: 0,
  writer: null,
  engine: { enabled: true, running: true },
}

const ROUTES = [
  ['GET', '/health', json(HEALTHY)],
  ['GET', '/groups', json(page([makeGroup()]))],
  ['GET', '/risk', risk],
  ['GET', '/trades', json(page([]))],
  ['GET', '/signals', json(page([]))],
  ['GET', '/reports/summary', json(makeSummary())],
  ['GET', '/reports/equity', json(makeEquity())],
  ['GET', '/reports/depth', json(makeDepth())],
  ['GET', '/reports/breakdown', json(makeBreakdown('group', []))],
] as const

async function renderApp(
  path: string,
  status: Snapshot | null = makeSnapshot(),
  feed = 'live' as const,
) {
  mockApi(ROUTES)
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  if (status !== null) client.setQueryData(keys.status, status)
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(
    <QueryClientProvider client={client}>
      <LiveStatusContext.Provider value={feed}>
        <RouterProvider router={router} />
      </LiveStatusContext.Provider>
    </QueryClientProvider>,
  )
  await screen.findByRole('navigation', { name: 'Main' }) // routes load their code on demand
  return view
}

describe('the app shell', () => {
  it('has a main navigation to every page', async () => {
    await renderApp('/')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    for (const name of ['Live', 'Signals', 'Groups', 'History', 'Reports']) {
      expect(within(nav).getByRole('link', { name })).toBeInTheDocument()
    }
    expect(await screen.findByRole('heading', { name: 'Live', level: 1 })).toBeInTheDocument()
  })

  it('marks the current page, and navigates (loading each page on demand)', async () => {
    const user = userEvent.setup()
    await renderApp('/')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Live' })).toHaveAttribute('aria-current', 'page')

    await user.click(within(nav).getByRole('link', { name: 'Groups' }))
    expect(await screen.findByRole('heading', { name: 'Groups' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Groups' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(within(nav).getByRole('link', { name: 'Live' })).not.toHaveAttribute('aria-current')

    await user.click(within(nav).getByRole('link', { name: 'History' }))
    expect(await screen.findByRole('heading', { name: 'Trade history' })).toBeInTheDocument()
    await user.click(within(nav).getByRole('link', { name: 'Signals' }))
    expect(await screen.findByRole('heading', { name: 'Signal inbox' })).toBeInTheDocument()
    await user.click(within(nav).getByRole('link', { name: 'Reports' }))
    expect(await screen.findByRole('heading', { name: 'Reports' })).toBeInTheDocument()
  })

  it('opens the group forms by address', async () => {
    await renderApp('/groups/new')
    expect(await screen.findByRole('heading', { name: 'Add a group' })).toBeInTheDocument()
  })

  it('has a page for addresses that do not exist', async () => {
    await renderApp('/nowhere')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the live page' })).toHaveAttribute('href', '/')
  })

  describe('the account indicator', () => {
    it('says DEMO on the demo account, with no warning banner', async () => {
      await renderApp('/')
      expect(screen.getByText('DEMO')).toBeInTheDocument()
      expect(screen.queryByText(/REAL MONEY/)).not.toBeInTheDocument()
    })

    it('is loud on the real account: a banner on every page and a red badge', async () => {
      await renderApp('/groups', makeSnapshot({ account_type: 'real' }))
      expect(screen.getByText('REAL MONEY')).toBeInTheDocument()
      expect(screen.getByRole('alert')).toHaveTextContent('REAL MONEY account')
      expect(screen.queryByText('DEMO')).not.toBeInTheDocument()
      await screen.findByRole('heading', { name: 'Groups' })
    })

    it('says it does not know yet rather than guessing', async () => {
      await renderApp('/', null)
      expect(screen.getByText('Account: loading…')).toBeInTheDocument()
      expect(screen.queryByText('DEMO')).not.toBeInTheDocument()
    })
  })

  describe('the connection badges', () => {
    it('show Telegram and Quotex as connected', async () => {
      await renderApp('/')
      expect(screen.getByText('Telegram: connected')).toBeInTheDocument()
      expect(screen.getByText('Quotex: connected')).toBeInTheDocument()
    })

    it('show a lost connection in words, not only colour', async () => {
      await renderApp(
        '/',
        makeSnapshot({
          connections: {
            quotex: { connected: false, detail: 'reconnecting', since: '2026-11-02T10:00:00Z' },
          },
        }),
      )
      expect(screen.getByText('Quotex: disconnected')).toBeInTheDocument()
      expect(screen.getByText('Telegram: waiting')).toBeInTheDocument()
    })

    it('say "not running" when the engine is off', async () => {
      await renderApp(
        '/',
        makeSnapshot({ engine: { enabled: false, running: false }, connections: {} }),
      )
      expect(screen.getByText('Telegram: not running')).toBeInTheDocument()
      expect(screen.getByText('Quotex: not running')).toBeInTheDocument()
    })

    it('show the state of the live feed', async () => {
      await renderApp('/')
      expect(screen.getByText('Feed: live')).toBeInTheDocument()
    })
  })

  it('keeps the kill switch in the header of every page', async () => {
    await renderApp('/history')
    expect(screen.getByRole('button', { name: 'Kill switch…' })).toBeInTheDocument()
    await screen.findByRole('heading', { name: 'Trade history' })
  })
})

describe('the error boundary', () => {
  it('shows a message instead of a blank page when part of the page crashes', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    function Broken(): never {
      throw new Error('boom in a table')
    }
    const user = userEvent.setup()
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('boom in a table')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })

  it('leaves the header (and the kill switch) working when a page crashes', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    mockApi([
      ...ROUTES.filter(([, path]) => path !== '/groups'),
      ['GET', '/groups', json({ not: 'a page' })],
    ])
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(keys.status, makeSnapshot())
    const router = createMemoryRouter(routes, { initialEntries: ['/groups'] })
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('This part of the page failed to draw')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Kill switch…' })).toBeInTheDocument()
    spy.mockRestore()
  })
})
