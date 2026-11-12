import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeChain, makeSession, makeSessionRun, makeSnapshot, page } from '../../test/fixtures'
import { apiError, json, mockApi, renderWith, testClient } from '../../test/utils'
import SessionsPage from './SessionsPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const quiet = [
  ['GET', '/groups', json(page([]))],
  ['GET', '/sessions/runs', json(page([]))],
] as const

const night = makeSession({
  id: 2,
  name: 'Night owl',
  enabled: false,
  start_time: '23:00:00',
  end_time: '01:00:00',
  repeat: 'once',
  weekdays: [],
  profit_target: null,
  loss_limit: null,
  mode: 'every_candle',
  max_open_pairs: 3,
  next_window_start: null,
  next_window_end: null,
})

describe('the sessions list', () => {
  it('lists each session with its window, strategy, stops and state', async () => {
    mockApi([['GET', '/sessions', json(page([makeSession(), night]))], ...quiet])
    renderWith(<SessionsPage />)

    const first = (await screen.findByText('London open')).closest('tr') as HTMLElement
    expect(within(first).getByText('EURUSD · 5 min')).toBeInTheDocument()
    expect(within(first).getByText('11:00–12:00')).toBeInTheDocument()
    expect(within(first).getByText('UTC · Mon–Fri')).toBeInTheDocument()
    expect(within(first).getByText('Flip every loss')).toBeInTheDocument()
    expect(within(first).getByText(/One pair at a time · base 1.00/)).toBeInTheDocument()
    expect(within(first).getByText('Profit 10.00')).toBeInTheDocument()
    expect(within(first).getByText('Loss 20.00')).toBeInTheDocument()
    expect(within(first).getByText('Enabled')).toBeInTheDocument()

    const second = screen.getByText('Night owl').closest('tr') as HTMLElement
    expect(within(second).getByText('23:00–01:00')).toBeInTheDocument()
    expect(within(second).getByText('UTC · Once')).toBeInTheDocument()
    expect(within(second).getByText(/A pair every candle, up to 3 open/)).toBeInTheDocument()
    expect(within(second).getByText('None')).toBeInTheDocument() // no targets
    expect(within(second).getByText('Disabled')).toBeInTheDocument()
  })

  it('invites the owner to add the first session', async () => {
    mockApi([['GET', '/sessions', json(page([]))], ...quiet])
    renderWith(<SessionsPage />)
    expect(await screen.findByText(/No sessions yet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add a session' })).toHaveAttribute(
      'href',
      '/sessions/new',
    )
  })

  it('shows the warnings the server gives, next to the session', async () => {
    mockApi([
      [
        'GET',
        '/sessions',
        json(page([makeSession({ warnings: ['The start time is not on a 5-minute boundary.'] })])),
      ],
      ...quiet,
    ])
    renderWith(<SessionsPage />)
    expect(await screen.findByRole('note')).toHaveTextContent(
      'London open: The start time is not on a 5-minute boundary.',
    )
  })

  it('says in words that stopping never cuts a chain off', async () => {
    mockApi([['GET', '/sessions', json(page([makeSession()]))], ...quiet])
    renderWith(<SessionsPage />)
    await screen.findByText('London open')
    expect(screen.getByText(/the chains already running always finish/)).toBeInTheDocument()
  })
})

describe('the buttons of a session', () => {
  it('starts a run now', async () => {
    const api = mockApi([
      ['GET', '/sessions', json(page([makeSession()]))],
      ['POST', '/sessions/1/start', json(makeSessionRun())],
      ...quiet,
    ])
    renderWith(<SessionsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Start London open now' }))
    await waitFor(() => {
      expect(api.to('POST', '/sessions/1/start')).toHaveLength(1)
    })
  })

  it('says why a session could not start (the engine is off, another is running)', async () => {
    mockApi([
      ['GET', '/sessions', json(page([makeSession()]))],
      [
        'POST',
        '/sessions/1/start',
        apiError(503, 'engine_not_running', 'The trading engine is not running.'),
      ],
      ...quiet,
    ])
    renderWith(<SessionsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Start London open now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'London open: The trading engine is not running.',
    )
  })

  it('cannot start a session that is switched off', async () => {
    mockApi([['GET', '/sessions', json(page([night]))], ...quiet])
    renderWith(<SessionsPage />)
    expect(await screen.findByRole('button', { name: 'Start Night owl now' })).toBeDisabled()
  })

  it('switches a session off and on again, sending everything else unchanged', async () => {
    const api = mockApi([
      ['GET', '/sessions', json(page([makeSession()]))],
      ['PUT', '/sessions/1', json(makeSession({ enabled: false }))],
      ...quiet,
    ])
    renderWith(<SessionsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Disable London open' }))
    await waitFor(() => {
      expect(api.to('PUT', '/sessions/1')).toHaveLength(1)
    })
    expect(api.to('PUT', '/sessions/1')[0]?.body).toMatchObject({
      name: 'London open',
      enabled: false,
      start_time: '11:00',
      weekdays: [0, 1, 2, 3, 4],
      profit_target: '10.00',
    })
  })

  it('asks before deleting, and says why a session with a history cannot go', async () => {
    const api = mockApi([
      ['GET', '/sessions', json(page([makeSession()]))],
      [
        'DELETE',
        '/sessions/1',
        apiError(409, 'session_in_use', 'the session has runs on record: disable it instead'),
      ],
      ...quiet,
    ])
    renderWith(<SessionsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Delete London open' }))
    expect(api.to('DELETE', '/sessions/1')).toHaveLength(0) // nothing yet: it asked first
    await userEvent.click(screen.getByRole('button', { name: 'Delete session' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('disable it instead')
  })
})

describe('a run in progress', () => {
  const run = makeSessionRun()
  const running = makeSession({ active_run: run })
  const snapshot = makeSnapshot({
    open_chains: [
      makeChain({ id: 'mine', group_id: 50, session_run_id: 'run-1', pair_no: 1 }),
      makeChain({ id: 'elsewhere', group_id: 7, asset: 'GBPUSD', session_run_id: null }),
    ],
  })

  it('shows its figures, its note and only its own chains', async () => {
    mockApi([
      ['GET', '/sessions', json(page([{ ...running }]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page([run]))],
    ])
    renderWith(<SessionsPage />, { client: testClient(snapshot) })

    const panel = (
      await screen.findByRole('heading', { name: 'Running now: London open' })
    ).closest('section') as HTMLElement
    expect(within(panel).getByText('Running')).toBeInTheDocument()
    expect(within(panel).getByText('+1.40')).toBeInTheDocument() // the profit so far
    expect(within(panel).getByText(/of a target of 10.00/)).toBeInTheDocument()
    expect(within(panel).getByText('Pairs opened').nextElementSibling).toHaveTextContent('2')
    expect(within(panel).getByText('Rounds skipped').nextElementSibling).toHaveTextContent('1')
    expect(within(panel).getByText('EURUSD')).toBeInTheDocument() // its chain...
    expect(within(panel).queryByText('GBPUSD')).not.toBeInTheDocument() // ...and not the other
  })

  it('shows a lopsided pair and the last note when there are any', async () => {
    const odd = makeSession({
      active_run: makeSessionRun({ lopsided_pairs: 1, note: 'pair 2: only one leg is running' }),
    })
    mockApi([
      ['GET', '/sessions', json(page([odd]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page([]))],
    ])
    renderWith(<SessionsPage />, { client: testClient(snapshot) })
    expect(await screen.findByText('Pairs with one leg only')).toBeInTheDocument()
    expect(screen.getByText(/Last note: pair 2: only one leg is running/)).toBeInTheDocument()
  })

  it('says it is stopping while the chains finish', async () => {
    const stopping = makeSession({ active_run: makeSessionRun({ state: 'stopping' }) })
    mockApi([
      ['GET', '/sessions', json(page([stopping]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page([]))],
    ])
    renderWith(<SessionsPage />, { client: testClient(snapshot) })
    expect(
      await screen.findByText('Stopping: no new pairs, running chains finish'),
    ).toBeInTheDocument()
  })

  it('asks before stopping, says the chains are not cut off, and then stops', async () => {
    const api = mockApi([
      ['GET', '/sessions', json(page([running]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page([]))],
      ['POST', '/sessions/1/stop', json(makeSessionRun({ state: 'stopping' }))],
    ])
    renderWith(<SessionsPage />, { client: testClient(snapshot) })
    const panel = (
      await screen.findByRole('heading', { name: 'Running now: London open' })
    ).closest('section') as HTMLElement
    await userEvent.click(within(panel).getByRole('button', { name: 'Stop London open' }))
    expect(api.to('POST', '/sessions/1/stop')).toHaveLength(0) // it asked first
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('not cut off')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Stop the session' }))
    await waitFor(() => {
      expect(api.to('POST', '/sessions/1/stop')).toHaveLength(1)
    })
  })

  it('cannot be edited, switched off or deleted while it runs', async () => {
    mockApi([
      ['GET', '/sessions', json(page([running]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page([]))],
    ])
    renderWith(<SessionsPage />, { client: testClient(snapshot) })
    expect(await screen.findByRole('button', { name: 'Disable London open' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Delete London open' })).toBeDisabled()
  })
})

describe('the history of runs', () => {
  it('lists past runs with how each ended and what it made', async () => {
    const runs = [
      makeSessionRun({
        id: 'a',
        state: 'ended',
        end_reason: 'profit_target',
        ended_at: '2026-11-02T10:40:00Z',
        profit: '10.40',
      }),
      makeSessionRun({
        id: 'b',
        state: 'ended',
        end_reason: 'interrupted',
        ended_at: '2026-11-01T11:10:00Z',
        profit: '-3.00',
        note: 'the application stopped while this run was in progress',
      }),
    ]
    mockApi([
      ['GET', '/sessions', json(page([makeSession()]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page(runs))],
    ])
    renderWith(<SessionsPage />)
    const table = await screen.findByRole('table', { name: /Runs of the trading sessions/ })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0] as HTMLElement).getByText('Profit target reached')).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).getByText('+10.40')).toBeInTheDocument()
    expect(within(rows[0] as HTMLElement).getByText('London open')).toBeInTheDocument()
    expect(
      within(rows[1] as HTMLElement).getByText('The application stopped while it ran'),
    ).toBeInTheDocument()
    expect(within(rows[1] as HTMLElement).getByText('-3.00')).toBeInTheDocument()
  })

  it('says when no session has run yet', async () => {
    mockApi([
      ['GET', '/sessions', json(page([makeSession()]))],
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions/runs', json(page([]))],
    ])
    renderWith(<SessionsPage />)
    expect(await screen.findByText('No session has run yet.')).toBeInTheDocument()
  })
})
