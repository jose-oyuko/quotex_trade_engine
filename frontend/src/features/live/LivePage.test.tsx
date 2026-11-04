import { act, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../../api/queries'
import {
  makeChain,
  makeGroup,
  makeSnapshot,
  makeSignal,
  makeTrade,
  page,
} from '../../test/fixtures'
import { json, mockApi, renderWith, testClient } from '../../test/utils'
import LivePage from './LivePage'

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date('2026-11-02T10:00:20Z') })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const risk = (pnl: string | null) =>
  json({
    controls: makeSnapshot().controls,
    day: pnl === null ? null : { account_type: 'demo', since: '2026-11-02T00:00:00Z', pnl },
    open_trades: 0,
    open_exposure: '0',
  })

function routes(extra: Parameters<typeof mockApi>[0] = []) {
  return [
    ['GET', '/groups', json(page([makeGroup()]))],
    ['GET', '/risk', risk('-3.40')],
    [
      'GET',
      '/trades',
      json(
        page([
          makeTrade({
            latency: { signal_to_order_ms: 0.5, decision_to_order_ms: 0.1, order_ack_ms: 100 },
          }),
          makeTrade({
            id: 't2',
            latency: { signal_to_order_ms: 1.5, decision_to_order_ms: 0.1, order_ack_ms: 100 },
          }),
        ]),
      ),
    ],
    ['GET', '/signals', json(page([makeSignal()]))],
    ...extra,
  ] as const
}

describe('LivePage', () => {
  it('shows the balance, today’s result, what is open and the signal-to-order speed', async () => {
    mockApi(routes())
    renderWith(<LivePage />, {
      client: testClient(makeSnapshot({ open_chains: [makeChain()], open_trades: [makeTrade()] })),
    })
    const stats = screen.getByLabelText('Summary')
    expect(within(stats).getByText('Balance (DEMO)')).toBeInTheDocument()
    expect(within(stats).getByText('1,000.00')).toBeInTheDocument()
    expect(await within(stats).findByText('-3.40')).toHaveClass('money-loss')
    expect(within(stats).getByText('Chains running').nextSibling).toHaveTextContent('1')
    expect(within(stats).getByText('Trades open').nextSibling).toHaveTextContent('1')
    expect(await within(stats).findByText('0.50 ms')).toBeInTheDocument()
    expect(within(stats).getByText(/median 1.0 ms of the last 2/)).toBeInTheDocument()
  })

  it('shows the open chain and the open trade with a live countdown', () => {
    mockApi(routes())
    renderWith(<LivePage />, {
      client: testClient(
        makeSnapshot({
          open_chains: [makeChain({ step: 1 })],
          open_trades: [makeTrade({ expires_at: '2026-11-02T10:01:00Z' })],
        }),
      ),
    })
    expect(screen.getByText('Step 2 of 4')).toBeInTheDocument()
    const openTrades = screen.getByRole('table', { name: 'Trades open now' })
    expect(within(openTrades).getByText('0:40')).toBeInTheDocument() // 10:00:20 -> 10:01:00
    act(() => {
      vi.advanceTimersByTime(15_000)
    })
    expect(within(openTrades).getByText('0:25')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(within(openTrades).getByText('settling…')).toBeInTheDocument()
  })

  it('has empty states for the lists', () => {
    mockApi(routes())
    renderWith(<LivePage />)
    expect(screen.getByText(/No chains are running/)).toBeInTheDocument()
    expect(screen.getByText('No trades are open.')).toBeInTheDocument()
  })

  it('warns when the engine is not running', () => {
    mockApi(routes([['GET', '/risk', risk(null)]]))
    renderWith(<LivePage />, {
      client: testClient(
        makeSnapshot({ engine: { enabled: false, running: false, state: 'stopped', error: null } }),
      ),
    })
    const notice = screen.getByText(/trading engine is not running/)
    expect(notice).toHaveTextContent('Settings')
    expect(within(notice).getByRole('link', { name: 'Settings' })).toHaveAttribute(
      'href',
      '/settings',
    )
    expect(notice).toHaveAttribute('role', 'status')
  })

  it('follows the cache: a chain that appears in the status appears on the page', async () => {
    mockApi(routes())
    const { client } = renderWith(<LivePage />)
    expect(screen.getByText(/No chains are running/)).toBeInTheDocument()
    act(() => {
      client.setQueryData(
        keys.status,
        makeSnapshot({ open_chains: [makeChain({ asset: 'GBPUSD' })] }),
      )
    })
    expect(await screen.findByText('GBPUSD')).toBeInTheDocument()
  })
})
