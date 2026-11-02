import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  makeBreakdown,
  makeDepth,
  makeEquity,
  makeGroup,
  makeMetrics,
  makeSummary,
  page,
} from '../../test/fixtures'
import { apiError, json, mockApi, renderWith } from '../../test/utils'
import ReportsPage from './ReportsPage'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const GROUPS = [
  'GET',
  '/groups',
  json(page([makeGroup(), makeGroup({ id: 2, title: 'Beta' })])),
] as const

function routes(overrides: Parameters<typeof mockApi>[0] = []) {
  // the first route that matches answers, so the overrides go first
  return [
    ...overrides,
    GROUPS,
    ['GET', '/reports/summary', json(makeSummary())],
    ['GET', '/reports/equity', json(makeEquity())],
    ['GET', '/reports/depth', json(makeDepth())],
    [
      'GET',
      '/reports/breakdown',
      (call: { path: string }) => {
        const by = new URLSearchParams(call.path.split('?')[1]).get('by') as 'group'
        return json(
          makeBreakdown(by, [
            ['1', `${by} one`, 6, '-5.60'],
            ['2', `${by} two`, 3, '3.10'],
          ]),
        )
      },
    ],
  ] as const
}

/** The cells of the breakdown table (the chart repeats the labels, so look only in the table). */
const breakdownTable = async (name: RegExp | string = /Profit by/) =>
  within(await screen.findByRole('table', { name }))

const lastQuery = (api: ReturnType<typeof mockApi>, path: string) => {
  const call = api.calls.filter((c) => c.path.split('?')[0] === path).at(-1)
  return new URLSearchParams(call?.path.split('?')[1])
}

describe('ReportsPage', () => {
  it('shows the headline figures, with the sample size and what it means', async () => {
    mockApi(routes())
    renderWith(<ReportsPage />)
    const stats = await screen.findByLabelText('Report figures')
    expect(within(stats).getByText('-2.50')).toHaveClass('money-loss')
    expect(within(stats).getByText('44.4%')).toBeInTheDocument() // win rate
    expect(within(stats).getByText('4 won, 5 lost')).toBeInTheDocument()
    expect(within(stats).getByText('-13.2%')).toBeInTheDocument() // return on stakes
    expect(within(stats).getByText('9.00')).toBeInTheDocument() // biggest drawdown
    expect(within(stats).getByText('2 wins / 4 losses')).toBeInTheDocument()
    expect(within(stats).getByText('now: 2 wins in a row')).toBeInTheDocument()
    expect(screen.getByText('too few trades: 9 finished trades')).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Only 9 trades: far too few')
  })

  it('words a streak of one correctly', async () => {
    mockApi(
      routes([
        [
          'GET',
          '/reports/summary',
          json(makeSummary({ streaks: { longest_win: 1, longest_loss: 1, current: -1 } })),
        ],
      ]),
    )
    renderWith(<ReportsPage />)
    expect(await screen.findByText('now: 1 loss in a row')).toBeInTheDocument()
  })

  it('says what is missing from the figures', async () => {
    mockApi(routes())
    renderWith(<ReportsPage />)
    expect(
      await screen.findByText(/Not counted in these figures.*1 failed, 1 unknown, 1 still open/),
    ).toBeInTheDocument()
  })

  it('answers "is it really working?" in words, and refuses to over-read a short record', async () => {
    mockApi(routes())
    renderWith(<ReportsPage />)
    expect(await screen.findByText('Not enough trades to tell (9).')).toBeInTheDocument()
    expect(screen.getByText(/at least 30 finished trades/)).toBeInTheDocument()
  })

  it('says nothing about sample size when there are plenty of trades', async () => {
    mockApi(
      routes([
        [
          'GET',
          '/reports/summary',
          json(
            makeSummary({
              metrics: makeMetrics({ trades: 400, sample: 'ok' }),
              expectation: {
                breakeven_win_rate: 0.54,
                actual_win_rate: 0.6,
                edge: 0.06,
                z_score: 2.4,
                verdict: 'above_break_even',
              },
            }),
          ),
        ],
      ]),
    )
    renderWith(<ReportsPage />)
    expect(await screen.findByText(/Above break-even/)).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    expect(screen.getByText('enough trades: 400 finished trades')).toBeInTheDocument()
  })

  it('draws the profit curve with a description, and the numbers behind it', async () => {
    mockApi(routes())
    const user = userEvent.setup()
    renderWith(<ReportsPage />)
    const chart = await screen.findByRole('img', { name: 'Running total of profit, by day' })
    expect(chart).toHaveAccessibleDescription(/From 2026-11-02: 1\.40; to 2026-11-04: -2\.50/)
    await user.click(screen.getByText('Show the numbers'))
    const table = screen.getByRole('table', { name: 'Profit by day' })
    expect(within(table).getByText('-9.00')).toBeInTheDocument()
    expect(within(table).getAllByRole('row')).toHaveLength(4) // header + three days
  })

  describe('the breakdown tabs', () => {
    it('starts with groups and shows the figures and a chart', async () => {
      const api = mockApi(routes())
      renderWith(<ReportsPage />)
      expect((await breakdownTable(/Profit by group/)).getByText('group one')).toBeInTheDocument()
      expect(lastQuery(api, '/reports/breakdown').get('by')).toBe('group')
      expect(screen.getByRole('tab', { name: 'By group' })).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('img', { name: 'Profit by group' })).toBeInTheDocument()
    })

    it('switches the split and asks the server for it', async () => {
      const api = mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await breakdownTable(/Profit by group/)
      for (const [tab, by, chart] of [
        ['By asset', 'asset', 'Profit by asset'],
        ['By strategy', 'strategy', 'Profit by strategy'],
        ['By hour of day', 'hour', 'Profit by hour of day'],
        ['By weekday', 'weekday', 'Profit by weekday'],
      ] as const) {
        await user.click(screen.getByRole('tab', { name: tab }))
        expect((await breakdownTable(new RegExp(chart))).getByText(`${by} one`)).toBeInTheDocument()
        expect(lastQuery(api, '/reports/breakdown').get('by')).toBe(by)
        expect(screen.getByRole('img', { name: chart })).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
      }
    })

    it('fades rows with too few trades and labels every row’s sample size', async () => {
      mockApi(
        routes([
          [
            'GET',
            '/reports/breakdown',
            json(
              makeBreakdown('group', [
                ['1', 'Big group', 120, '10.00'],
                ['2', 'Mid group', 20, '1.00'],
                ['3', 'Tiny group', 4, '-3.00'],
              ]),
            ),
          ],
        ]),
      )
      renderWith(<ReportsPage />)
      const table = await breakdownTable(/Profit by group/)
      const big = table.getByText('Big group').closest('tr') as HTMLElement
      const mid = table.getByText('Mid group').closest('tr') as HTMLElement
      const tiny = table.getByText('Tiny group').closest('tr') as HTMLElement
      expect(within(big).getByText('enough trades')).toBeInTheDocument()
      expect(within(mid).getByText('small sample')).toBeInTheDocument()
      expect(within(tiny).getByText('too few trades')).toBeInTheDocument()
      expect(tiny).toHaveClass('row-faint')
      expect(big).not.toHaveClass('row-faint')
    })

    it('leaves quiet hours out of the table but keeps every hour on the chart', async () => {
      mockApi(
        routes([
          [
            'GET',
            '/reports/breakdown',
            json(
              makeBreakdown(
                'hour',
                Array.from({ length: 24 }, (_, h) => [
                  String(h),
                  `${String(h).padStart(2, '0')}:00`,
                  h === 9 || h === 14 ? 5 : 0,
                  h === 9 ? '-2.00' : h === 14 ? '1.50' : '0.00',
                ]),
              ),
            ),
          ],
        ]),
      )
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await user.click(await screen.findByRole('tab', { name: 'By hour of day' }))
      const table = await screen.findByRole('table', { name: /Profit by hour of day/ })
      expect(within(table).getAllByRole('row')).toHaveLength(3) // header, 09:00, 14:00
      expect(within(table).getByText('09:00')).toBeInTheDocument()
      expect(screen.getByText(/Hours with no trades are left out/)).toBeInTheDocument()
      const chart = screen.getByRole('img', { name: 'Profit by hour of day' })
      expect(chart.querySelectorAll('rect')).toHaveLength(24)
    })

    it('has an empty state', async () => {
      mockApi(routes([['GET', '/reports/breakdown', json(makeBreakdown('group', []))]]))
      renderWith(<ReportsPage />)
      expect(await screen.findByText('No finished trades in this range.')).toBeInTheDocument()
    })
  })

  it('shows how deep chains go and what each step cost', async () => {
    mockApi(routes())
    renderWith(<ReportsPage />)
    const chart = await screen.findByRole('img', {
      name: 'Share of chains that reached each trade',
    })
    expect(chart).toHaveAccessibleDescription(/Highest: Trade 1, 100\.0%/)
    expect(screen.getByText(/5 chains: 4 ended on a win, 1 lost every step/)).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'What each step of a chain cost' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(4)
    expect(within(rows[2] as HTMLElement).getByText('60.0%')).toBeInTheDocument()
  })

  describe('the filters', () => {
    it('start on the demo account for all time, and send only what is set', async () => {
      const api = mockApi(routes())
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      const query = lastQuery(api, '/reports/summary')
      expect(query.get('account_type')).toBe('demo')
      expect(query.has('from')).toBe(false)
      expect(query.has('group_id')).toBe(false)
      expect(query.get('utc_offset_minutes')).toMatch(/^-?\d+$/)
    })

    it('never mix demo and real: switching the account asks for the other one', async () => {
      const api = mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      await user.selectOptions(screen.getByLabelText('Account'), 'real')
      await waitFor(() => {
        expect(lastQuery(api, '/reports/summary').get('account_type')).toBe('real')
      })
      for (const path of ['/reports/equity', '/reports/depth', '/reports/breakdown']) {
        await waitFor(() => {
          expect(lastQuery(api, path).get('account_type')).toBe('real')
        })
      }
    })

    it('narrow every report by group, strategy and asset', async () => {
      const api = mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      await user.selectOptions(await screen.findByLabelText('Group'), 'Beta')
      await user.selectOptions(screen.getByLabelText('Strategy'), 'martingale')
      await user.type(screen.getByLabelText('Asset'), 'eurusd')
      await waitFor(() => {
        const q = lastQuery(api, '/reports/summary')
        expect([q.get('group_id'), q.get('strategy'), q.get('asset')]).toEqual([
          '2',
          'martingale',
          'EURUSD', // upper-cased for the owner
        ])
      })
      const depth = lastQuery(api, '/reports/depth')
      expect([depth.get('group_id'), depth.get('strategy')]).toEqual(['2', 'martingale'])
    })

    it('use the browser’s own clock for hours, days and the start of "today"', async () => {
      vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(180) // the browser is at UTC-3
      const api = mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      expect(lastQuery(api, '/reports/summary').get('utc_offset_minutes')).toBe('-180')
      expect(lastQuery(api, '/reports/breakdown').get('utc_offset_minutes')).toBe('-180')
      await user.selectOptions(screen.getByLabelText('Period'), 'today')
      await waitFor(() => {
        expect(lastQuery(api, '/reports/summary').has('from')).toBe(true)
      })
      // a day that starts at local midnight starts at 03:00 UTC
      expect(lastQuery(api, '/reports/summary').get('from')).toMatch(/T03:00:00\.000Z$/)
    })

    it('send the period as instants on the owner’s clock', async () => {
      const api = mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      await user.selectOptions(screen.getByLabelText('Period'), '7')
      await waitFor(() => {
        expect(lastQuery(api, '/reports/summary').has('from')).toBe(true)
      })
      const q = lastQuery(api, '/reports/summary')
      expect(q.get('from')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$/)
      expect(new Date(q.get('to') ?? '').getTime() - new Date(q.get('from') ?? '').getTime()).toBe(
        7 * 24 * 3600 * 1000,
      )
    })

    it('accept custom dates, and refuse a backwards range without asking the server', async () => {
      const api = mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      await user.selectOptions(screen.getByLabelText('Period'), 'custom')
      expect(screen.getByRole('alert')).toHaveTextContent('Pick the dates')
      await user.type(screen.getByLabelText('From'), '2026-11-05')
      await user.type(screen.getByLabelText('To (inclusive)'), '2026-11-02')
      expect(screen.getByRole('alert')).toHaveTextContent('cannot be before the start')
      expect(screen.queryByLabelText('Report figures')).not.toBeInTheDocument()
      const before = api.calls.length
      await user.clear(screen.getByLabelText('To (inclusive)'))
      await user.type(screen.getByLabelText('To (inclusive)'), '2026-11-06')
      await waitFor(() => {
        expect(api.calls.length).toBeGreaterThan(before)
      })
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      const q = lastQuery(api, '/reports/summary')
      expect(q.get('from')).toBeTruthy()
      expect(q.get('to')).toBeTruthy()
    })
  })

  describe('the downloads', () => {
    it('link to the trades file and to each breakdown, carrying the filters', async () => {
      mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      await user.selectOptions(screen.getByLabelText('Account'), 'real')
      await user.selectOptions(await screen.findByLabelText('Group'), 'Beta')
      const trades = await screen.findByRole('link', { name: 'Download all trades (CSV)' })
      await waitFor(() => {
        expect(trades.getAttribute('href')).toContain('account_type=real')
      })
      const href = trades.getAttribute('href') ?? ''
      expect(href.startsWith('/api/v1/reports/export/trades.csv?')).toBe(true)
      expect(href).toContain('group_id=2')
      expect(href).toContain('delimiter=comma')
      expect(trades).toHaveAttribute('download')
      const byAsset = screen.getByRole('link', { name: 'By asset (CSV)' })
      expect(byAsset.getAttribute('href')).toContain('/reports/export/breakdown.csv?')
      expect(byAsset.getAttribute('href')).toContain('by=asset')
      expect(screen.getByRole('link', { name: 'By hour of day (CSV)' })).toBeInTheDocument()
    })

    it('offer a semicolon version for Excel in many locales', async () => {
      mockApi(routes())
      const user = userEvent.setup()
      renderWith(<ReportsPage />)
      await screen.findByLabelText('Report figures')
      await user.selectOptions(screen.getByLabelText(/Column separator/), 'semicolon')
      expect(
        screen.getByRole('link', { name: 'Download all trades (CSV)' }).getAttribute('href'),
      ).toContain('delimiter=semicolon')
    })
  })

  it('has an empty state when the account has no trades', async () => {
    mockApi(
      routes([
        [
          'GET',
          '/reports/summary',
          json(
            makeSummary({
              metrics: makeMetrics({ trades: 0, wins: 0, losses: 0, win_rate: null, roi: null }),
              not_counted: { failed: 0, unknown: 0, open: 0 },
            }),
          ),
        ],
      ]),
    )
    renderWith(<ReportsPage />)
    expect(await screen.findByText(/No trades in this period for this account/)).toBeInTheDocument()
  })

  it('shows a failure with a way to retry, without hiding the other reports', async () => {
    mockApi(
      routes([
        ['GET', '/reports/summary', apiError(500, 'internal_error', 'Something went wrong')],
      ]),
    )
    renderWith(<ReportsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: /Running total/ })).toBeInTheDocument()
  })
})
