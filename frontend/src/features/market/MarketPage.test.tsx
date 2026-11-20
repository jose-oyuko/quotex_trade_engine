import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Candles, PricesOut, Scan } from '../../api/types'
import { apiError, json, mockApi, renderWith, type Call } from '../../test/utils'
import type { CandleChartProps } from './CandleChart'
import MarketPage from './MarketPage'

// The real chart draws on a canvas, which the test browser does not have: a stand-in records what
// the page asks it to draw and show.
const chart = vi.hoisted(() => ({ props: null as CandleChartProps | null }))
vi.mock('./CandleChart', () => ({
  CandleChart: (props: CandleChartProps) => {
    chart.props = props
    return <div data-testid="chart">{props.candles.length} candles</div>
  },
}))

const at = (iso: string) => Date.parse(iso) / 1000

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

const names = {
  available: true,
  reason: null,
  items: [{ asset: '1HZ75V', name: 'Volatility 75 (1s) Index', group: 'Volatility indices' }],
}

const patterns = {
  items: [
    {
      pattern: 'alternating',
      candles: 5,
      misses: 1,
      width: 2,
      net_share: 0.2,
      breakout_candles: 2,
      breakout_by: 'close',
    },
    {
      pattern: 'mixed',
      candles: 6,
      misses: 1,
      width: 2,
      net_share: 0.2,
      breakout_candles: 2,
      breakout_by: 'close',
    },
  ],
}

function candles(call: Call): Response {
  const query = new URLSearchParams(call.path.split('?')[1])
  const length = Number(query.get('length'))
  const start = at(query.get('start') ?? '')
  const body: Candles = {
    asset: '1HZ75V',
    length,
    start: query.get('start') ?? '',
    end: query.get('end') ?? '',
    items: [0, 1, 2].map((i) => ({
      start: new Date((start + i * length) * 1000).toISOString().replace('.000Z', 'Z'),
      open: 100,
      high: 102,
      low: 99,
      close: 101,
      ticks: length,
    })),
  }
  return json(body)
}

const rate = (hits: number, total: number) => ({
  hits,
  total,
  share: hits / total,
  low: 0.02,
  high: 0.05,
})

const scan: Scan = {
  asset: '1HZ75V',
  length: 60,
  start: '2026-11-17T23:00:00Z',
  end: '2026-11-18T23:00:00Z',
  rules: {
    pattern: 'mixed',
    candles: 6,
    misses: 1,
    width: 2,
    net_share: 0.2,
    breakout_candles: 2,
    breakout_by: 'close',
  },
  consolidations: [
    {
      first: '2026-11-18T10:00:00Z',
      found: '2026-11-18T10:06:00Z',
      end: '2026-11-18T10:08:00Z',
      candles: 8,
      high: 1210.5,
      low: 1201.25,
      breakout: {
        start: '2026-11-18T10:08:00Z',
        known: '2026-11-18T10:10:00Z',
        direction: 'up',
        level: 1210.5,
        close: 1212,
      },
      ended: 'breakout',
    },
    {
      first: '2026-11-18T10:30:00Z',
      found: '2026-11-18T10:36:00Z',
      end: '2026-11-18T10:40:00Z',
      candles: 10,
      high: 1215,
      low: 1207,
      breakout: null,
      ended: 'end',
    },
  ],
  trends: [
    {
      start: '2026-11-18T10:10:00Z',
      end: '2026-11-18T10:30:00Z',
      stopped: '2026-11-18T10:36:00Z',
      direction: 'up',
      candles: 20,
      open: 1212,
      close: 1209,
      move: -3,
      ended: 'consolidation',
    },
  ],
  stats: {
    candles: 1440,
    consolidations: 2,
    breakouts: 1,
    in_consolidation: 0.0125,
    trend_wait: { count: 1, mean: 26, median: 26, q1: 26, q3: 26, longest: 26 },
    any_wait: { count: 1400, mean: 22, median: 21, q1: 11, q3: 35, longest: 150 },
    first_with: rate(1, 1),
    trend_with: rate(10, 20),
    break_even: 0.5319,
    deep: 6,
    deep_any: rate(50, 1400),
    deep_trend: rate(1, 26),
    deep_consolidation: rate(0, 6),
    described: rate(9, 10),
  },
}

const base = [
  ['GET', '/prices', json(held)],
  ['GET', '/prices/assets', json(names)],
  ['GET', '/market/patterns', json(patterns)],
  ['GET', /^\/market\/candles\?/, candles],
] as const

beforeEach(() => {
  chart.props = null
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function props(): CandleChartProps {
  if (chart.props === null) throw new Error('the chart was not drawn')
  return chart.props
}

describe('MarketPage', () => {
  it('draws the newest stored candles, and other timeframes on request', async () => {
    const api = mockApi([...base])
    const user = userEvent.setup()
    renderWith(<MarketPage />, { route: '/market' })
    await waitFor(() => {
      expect(screen.getByLabelText('Asset')).toHaveDisplayValue('Volatility 75 (1s) Index (1HZ75V)')
    })
    await waitFor(() => {
      expect(props().candles.length).toBeGreaterThan(0)
    })
    const m1 = api.calls.filter((c) => c.path.startsWith('/market/candles'))
    expect(m1.length).toBeGreaterThan(0)
    expect(m1.every((c) => c.path.includes('length=60'))).toBe(true)
    // the chart is asked to show the end of what is stored
    expect(props().focus?.to).toBe(at('2026-11-18T23:59:59Z'))

    await user.click(screen.getByRole('button', { name: 'M5' }))
    expect(screen.getByRole('button', { name: 'M5' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => {
      expect(api.calls.some((c) => c.path.includes('length=300'))).toBe(true)
    })
    expect(props().length).toBe(300)

    await user.type(screen.getByLabelText(/or seconds/), '90')
    await user.click(screen.getByRole('button', { name: 'Use' }))
    await waitFor(() => {
      expect(api.calls.some((c) => c.path.includes('length=90'))).toBe(true)
    })
  })

  it('jumps to a date and loads the candles around it', async () => {
    const api = mockApi([...base])
    const user = userEvent.setup()
    renderWith(<MarketPage />, { route: '/market' })
    await screen.findByTestId('chart')
    fireEvent.change(screen.getByLabelText('Go to (UTC)'), {
      target: { value: '2026-11-18T03:30' },
    })
    await user.click(screen.getByRole('button', { name: 'Go' }))
    const target = at('2026-11-18T03:30:00Z')
    expect(props().focus?.from).toBe(target)
    await waitFor(() => {
      const starts = api.calls
        .filter((c) => c.path.startsWith('/market/candles'))
        .map((c) => at(new URLSearchParams(c.path.split('?')[1]).get('start') ?? ''))
      expect(starts.some((s) => s <= target && target < s + 60_000)).toBe(true)
    })
  })

  it('scans with the chosen definition and marks the chart from the answer', async () => {
    const api = mockApi([...base, ['POST', '/market/scan', json(scan)]])
    const user = userEvent.setup()
    renderWith(<MarketPage />, { route: '/market' })
    const form = await screen.findByRole('form', { name: 'Find consolidations' })
    await waitFor(() => {
      expect(within(form).getByLabelText('From (UTC)')).toHaveValue('2026-11-18T00:00')
    })

    await user.selectOptions(within(form).getByLabelText('Pattern'), 'mixed')
    const candles = within(form).getByLabelText('Candles in the pattern')
    expect(candles).toHaveValue('6') // the pattern's own default
    expect(within(form).getByLabelText('Candles that may not alternate')).toHaveValue('1')
    await user.clear(candles)
    await user.type(candles, '1')
    await user.click(within(form).getByRole('button', { name: 'Scan' }))
    expect(await within(form).findByText('From 2 to 50 candles')).toBeVisible()
    expect(api.to('POST', '/market/scan')).toHaveLength(0)

    await user.clear(candles)
    await user.type(candles, '6')
    await user.selectOptions(within(form).getByLabelText('Breakout by'), 'touch')
    await user.click(within(form).getByRole('button', { name: 'Scan' }))
    await waitFor(() => {
      expect(api.to('POST', '/market/scan')).toHaveLength(1)
    })
    const body = api.to('POST', '/market/scan')[0]?.body as Record<string, unknown>
    expect(body).toMatchObject({
      asset: '1HZ75V',
      length: 60,
      start: '2026-11-18T00:00:00Z',
      rules: { pattern: 'mixed', candles: 6, misses: 1, breakout_by: 'touch' },
    })

    expect(await screen.findByText(/2 consolidations \(1 broke out\)/)).toBeVisible()
    expect(screen.getByText(/no real difference/)).toBeVisible()
    const table = screen.getByRole('table', { name: 'Consolidations found' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(within(rows[0] as HTMLElement).getByText('↑ up')).toBeVisible()
    expect(within(rows[0] as HTMLElement).getByText('20 candles (20 min)')).toBeVisible()
    expect(within(rows[1] as HTMLElement).getByText('none yet')).toBeVisible()

    // the marks are the server's answer, as it gave them
    const { zones, markers } = props()
    expect(zones).toContainEqual({
      from: at('2026-11-18T10:00:00Z'),
      to: at('2026-11-18T10:08:00Z'),
      top: 1210.5,
      bottom: 1201.25,
      kind: 'consolidation',
      selected: false,
    })
    expect(zones).toContainEqual(
      expect.objectContaining({ from: at('2026-11-18T10:10:00Z'), kind: 'up', top: null }),
    )
    expect(markers).toEqual([{ time: at('2026-11-18T10:09:00Z'), direction: 'up' }])
  })

  it('shows a consolidation on the chart when its row is chosen', async () => {
    mockApi([...base, ['POST', '/market/scan', json(scan)]])
    const user = userEvent.setup()
    renderWith(<MarketPage />, { route: '/market' })
    await user.click(await screen.findByRole('button', { name: 'Scan' }))
    const table = await screen.findByRole('table', { name: 'Consolidations found' })
    const second = within(table).getAllByRole('button', { name: 'Show' })[1] as HTMLElement
    await user.click(second)
    expect(second).toHaveAttribute('aria-pressed', 'true')
    const { focus, zones } = props()
    expect(focus).toMatchObject({
      from: at('2026-11-18T10:30:00Z'),
      to: at('2026-11-18T10:40:00Z'),
    })
    const marked = zones.filter((z) => z.selected)
    expect(marked).toEqual([expect.objectContaining({ from: at('2026-11-18T10:30:00Z') })])
    // the first one, with the trend after it, is shown up to the trend's end
    await user.click(within(table).getAllByRole('button', { name: 'Show' })[0] as HTMLElement)
    expect(props().focus?.to).toBe(at('2026-11-18T10:30:00Z'))
  })

  it('shows the server’s refusal in words', async () => {
    mockApi([
      ...base,
      [
        'POST',
        '/market/scan',
        apiError(422, 'invalid_market', 'No prices of 1HZ75V are stored from …: download them.'),
      ],
    ])
    const user = userEvent.setup()
    renderWith(<MarketPage />, { route: '/market' })
    await user.click(await screen.findByRole('button', { name: 'Scan' }))
    expect(await screen.findByText(/No prices of 1HZ75V are stored/)).toBeVisible()
  })

  it('sends the owner to the Backtest page when no prices are stored', async () => {
    mockApi([...base.slice(1), ['GET', '/prices', json({ items: [], running: null })]])
    renderWith(<MarketPage />, { route: '/market' })
    expect(await screen.findByRole('link', { name: 'Backtest' })).toHaveAttribute(
      'href',
      '/backtest',
    )
  })
})
