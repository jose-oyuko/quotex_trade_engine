import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Backtest, BacktestChains, Download, PricesOut } from '../../api/types'
import { apiError, json, mockApi, renderWith } from '../../test/utils'
import BacktestPage from './BacktestPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const held: PricesOut = {
  items: [
    {
      asset: '1HZ75V',
      ticks: 86_400,
      first: '2026-11-18T00:00:00Z',
      last: '2026-11-18T23:59:59Z',
      ranges: [{ start: '2026-11-18T00:00:00Z', end: '2026-11-18T23:59:59Z' }],
    },
  ],
  running: null,
}

function download(overrides: Partial<Download> = {}): Download {
  return {
    id: 7,
    asset: '1HZ75V',
    start: '2026-11-18T00:00:00Z',
    end: '2026-11-19T00:00:00Z',
    state: 'running',
    ticks: 25_000,
    progress: 0.3,
    note: null,
    error: null,
    created_at: '2026-11-19T10:00:00Z',
    finished_at: null,
    ...overrides,
  }
}

const strategy = {
  windows: 1,
  pairs: 30,
  chains: 60,
  trades: 90,
  trades_won: 45,
  won_at_step: [30, 15, 5, 0],
  exhausted: 10,
  no_data_chains: 0,
  skipped_rounds: 2,
  no_data_rounds: 0,
  profit: '-4.20',
  staked: '150.00',
  largest_stake: '8.00',
  most_in_play: '12.00',
  worst_drawdown: '20.50',
  worst_drawdown_at: '2026-11-18T11:00:00Z',
  longest_losing_run: 3,
  stops: { window_ended: 1 },
  days: [{ day: '2026-11-18', profit: '-4.20', chains: 60, lost: 10 }],
  equity: [
    { at: '2026-11-18T10:01:00Z', profit: '-1.00' },
    { at: '2026-11-18T13:59:00Z', profit: '-4.20' },
  ],
}

function backtest(overrides: Partial<Backtest> = {}): Backtest {
  return {
    id: 3,
    name: '1HZ75V 1m, 2026-11-18',
    state: 'done',
    progress: 1,
    error: null,
    created_at: '2026-11-19T10:00:00Z',
    finished_at: '2026-11-19T10:00:05Z',
    asset: '1HZ75V',
    first_day: '2026-11-18',
    last_day: '2026-11-18',
    strategies: ['martingale'],
    setup: {
      name: null,
      asset: '1HZ75V',
      first_day: '2026-11-18',
      last_day: '2026-11-18',
      start_time: '10:00:00',
      end_time: '14:00:00',
      timezone: 'UTC',
      weekdays: [0, 1, 2, 3, 4, 5, 6],
      duration_s: 60,
      mode: 'sequential',
      pause_s: 0,
      max_open_pairs: 1,
      max_pairs: null,
      profit_target: null,
      loss_limit: null,
      base_stake: '1.00',
      strategies: [{ strategy: 'martingale', max_steps: 3, multipliers: ['2', '4', '8'] }],
      payout_pct: '88',
      order_delay_s: 0.5,
      step_delay_s: 1,
    },
    summary: {
      windows: 1,
      seconds: 0.4,
      strategies: [
        { strategy: 'martingale', max_steps: 3, multipliers: ['2', '4', '8'], ...strategy },
      ],
    },
    ...overrides,
  }
}

const chains: BacktestChains = {
  total: 1,
  items: [
    {
      strategy: 0,
      seq: 1,
      day: '2026-11-18',
      pair_no: 1,
      origin: 'call',
      started: '2026-11-18T10:00:00Z',
      status: 'exhausted',
      steps: 2,
      profit: '-3.00',
      trades: [
        {
          start: '2026-11-18T10:00:00Z',
          end: '2026-11-18T10:01:00Z',
          direction: 'call',
          stake: '1.00',
          entry: 100.1,
          exit: 100.0,
          profit: '-1.00',
        },
        {
          start: '2026-11-18T10:01:01Z',
          end: '2026-11-18T10:02:01Z',
          direction: 'call',
          stake: '2.00',
          entry: 100.0,
          exit: 99.0,
          profit: '-2.00',
        },
      ],
    },
  ],
}

const names = {
  available: true,
  reason: null,
  items: [
    { asset: '1HZ75V', name: 'Volatility 75 (1s) Index', group: 'Volatility indices' },
    { asset: 'R_75', name: 'Volatility 75 Index', group: 'Volatility indices' },
    { asset: 'BOOM500', name: 'Boom 500 Index', group: 'Crash and Boom' },
  ],
}

const base = [
  ['GET', '/prices/assets', json(names)],
  ['GET', '/prices', json(held)],
  ['GET', '/prices/downloads', json({ items: [download({ state: 'done', progress: 1 })] })],
  ['GET', '/backtests', json({ items: [] })],
  ['GET', '/sessions', json({ items: [], total: 0, limit: 200, offset: 0 })],
] as const

describe('the Backtest page', () => {
  it('lists the stored prices and starts a download', async () => {
    const api = mockApi([...base, ['POST', '/prices/downloads', json(download(), 202)]])
    const user = userEvent.setup()
    renderWith(<BacktestPage />, { route: '/backtest' })
    const table = await screen.findByRole('table', { name: 'Stored prices' })
    expect(await within(table).findByText('Volatility 75 (1s) Index (1HZ75V)')).toBeVisible()
    expect(within(table).getByText('86,400')).toBeVisible()
    const form = screen.getByRole('form', { name: 'Download prices' })
    const picker = within(form).getByLabelText('Asset')
    expect(within(picker).getByRole('option', { name: 'Boom 500 Index (BOOM500)' })).toBeVisible()
    await user.selectOptions(picker, 'Volatility 75 Index (R_75)')
    await user.click(within(form).getByRole('button', { name: 'Download' }))
    await waitFor(() => {
      expect(api.to('POST', '/prices/downloads')).toHaveLength(1)
    })
    const body = api.to('POST', '/prices/downloads')[0]?.body as Record<string, string>
    expect(body.asset).toBe('R_75')
    expect(body.start).toMatch(/T00:00:00Z$/)
  })

  it('shows a running download with its progress and cancels it', async () => {
    const api = mockApi([
      ['GET', '/prices/assets', json(names)],
      ['GET', '/prices', json({ ...held, running: download() })],
      ...base.slice(2),
      ['POST', '/prices/downloads/7/cancel', json(download({ state: 'cancelled' }))],
    ])
    const user = userEvent.setup()
    renderWith(<BacktestPage />, { route: '/backtest' })
    expect(await screen.findByRole('progressbar', { name: 'Download 30% done' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Download' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => {
      expect(api.to('POST', '/prices/downloads/7/cancel')).toHaveLength(1)
    })
  })

  it('runs a backtest with several strategies and opens it', async () => {
    const api = mockApi([
      ...base,
      ['POST', '/backtests', json(backtest({ state: 'running', summary: null, progress: 0 }), 202)],
      ['GET', '/backtests/3', json(backtest({ state: 'running', summary: null, progress: 0.5 }))],
    ])
    const user = userEvent.setup()
    renderWith(<BacktestPage />, { route: '/backtest' })
    await screen.findByRole('table', { name: 'Stored prices' })
    await user.click(screen.getByRole('button', { name: 'Run the backtest' }))
    await waitFor(() => {
      expect(api.to('POST', '/backtests')).toHaveLength(1)
    })
    const body = api.to('POST', '/backtests')[0]?.body as {
      strategies: unknown[]
      asset: string
      name: string
    }
    expect(body.asset).toBe('1HZ75V')
    expect(body.name).toMatch(/^Volatility 75 \(1s\) Index \(1HZ75V\), \d{4}-\d{2}-\d{2}$/)
    expect(body.strategies).toHaveLength(2)
    expect(await screen.findByRole('progressbar', { name: 'Backtest 50% done' })).toBeVisible()
  })

  it('refuses a 9th growing flip step before sending anything', async () => {
    const api = mockApi(base)
    const user = userEvent.setup()
    renderWith(<BacktestPage />, { route: '/backtest' })
    await screen.findByRole('table', { name: 'Stored prices' })
    const growing = screen.getByDisplayValue('2, 4, 8, 16, 32, 64, 128, 256')
    await user.type(growing, ', 512')
    await user.click(screen.getByRole('button', { name: 'Run the backtest' }))
    expect(
      await screen.findByText('Growing flip has at most 8 steps (9 trades in all)'),
    ).toBeVisible()
    expect(api.to('POST', '/backtests')).toHaveLength(0)
  })

  it('shows the server’s refusal in words', async () => {
    mockApi([
      ...base,
      [
        'POST',
        '/backtests',
        apiError(
          422,
          'invalid_backtest',
          'No prices of 1HZ75V are stored for these days: download them first.',
        ),
      ],
    ])
    const user = userEvent.setup()
    renderWith(<BacktestPage />, { route: '/backtest' })
    await screen.findByRole('table', { name: 'Stored prices' })
    await user.click(screen.getByRole('button', { name: 'Run the backtest' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('download them first')
  })

  it('shows a finished backtest: the comparison, the assumptions and the chains', async () => {
    mockApi([
      ...base.slice(0, 3),
      ['GET', '/backtests', json({ items: [backtest()] })],
      ['GET', '/sessions', json({ items: [], total: 0, limit: 200, offset: 0 })],
      ['GET', '/backtests/3', json(backtest())],
      ['GET', /^\/backtests\/3\/chains/, json(chains)],
    ])
    renderWith(<BacktestPage />, { route: '/backtest?run=3' })
    const table = await screen.findByRole('table', { name: 'The strategies compared' })
    expect(within(table).getByRole('columnheader', { name: 'Martingale ×2, 4, 8' })).toBeVisible()
    const row = within(table).getByRole('row', { name: /Chains lost \(every step\)/ })
    expect(row).toHaveTextContent('10 (16.7%)')
    expect(screen.getByRole('note')).toHaveTextContent('payout of 88%')
    expect(screen.getByRole('note')).toHaveTextContent('not a prediction')
    const list = await screen.findByRole('table', { name: 'Chains of the backtest' })
    expect(within(list).getByText('lost every step')).toBeVisible()
    expect(within(list).getByText('2 trade(s)')).toBeVisible()
  })
})
