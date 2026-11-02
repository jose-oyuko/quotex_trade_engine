import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Trade } from '../../api/types'
import { makeGroup, makeTrade, page } from '../../test/fixtures'
import { apiError, json, mockApi, renderWith } from '../../test/utils'
import HistoryPage from './HistoryPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const GROUPS = [
  'GET',
  '/groups',
  json(page([makeGroup(), makeGroup({ id: 2, title: 'Beta' })])),
] as const

/** A fake server holding `total` trades, answering each page the way the real one does. */
function tradesServer(total: number) {
  const all: Trade[] = Array.from({ length: total }, (_, i) =>
    makeTrade({ id: `t${String(i)}`, asset: `ASSET${String(i)}`, status: 'won', profit: '0.85' }),
  )
  return [
    'GET',
    '/trades',
    (call: { path: string }) => {
      const query = new URLSearchParams(call.path.split('?')[1])
      const limit = Number(query.get('limit'))
      const offset = Number(query.get('offset'))
      const status = query.get('status')
      const rows = status === null ? all : all.filter((t) => t.status === status)
      return json({ items: rows.slice(offset, offset + limit), total: rows.length, limit, offset })
    },
  ] as const
}

const dataRows = () => screen.getAllByRole('row').slice(1) // without the header row

describe('HistoryPage', () => {
  it('shows a loading state, then the trades', async () => {
    mockApi([GROUPS, tradesServer(3)])
    renderWith(<HistoryPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    expect(await screen.findByText('ASSET0')).toBeInTheDocument()
    expect(dataRows()).toHaveLength(3)
  })

  it('shows what a trade was: result, profit with its sign, payout and the speed', async () => {
    mockApi([
      GROUPS,
      [
        'GET',
        '/trades',
        json(
          page([
            makeTrade({ status: 'lost', profit: '-1.00', payout_pct: 85 }),
            makeTrade({ id: 't2', status: 'won', profit: '0.85', asset: 'GBPUSD' }),
          ]),
        ),
      ],
    ])
    renderWith(<HistoryPage />)
    const lost = (await screen.findByText('-1.00')).closest('tr') as HTMLElement
    expect(within(lost).getByText('Lost')).toBeInTheDocument()
    expect(within(lost).getByText('85%')).toBeInTheDocument()
    expect(within(lost).getByText('0.40 ms')).toBeInTheDocument()
    expect(screen.getByText('+0.85')).toBeInTheDocument()
  })

  it('says when there is nothing to show', async () => {
    mockApi([GROUPS, ['GET', '/trades', json(page([]))]])
    renderWith(<HistoryPage />)
    expect(await screen.findByText(/No trades match/)).toBeInTheDocument()
  })

  it('says what went wrong, and tries again on request', async () => {
    let fail = true
    mockApi([
      GROUPS,
      [
        'GET',
        '/trades',
        () =>
          fail
            ? apiError(500, 'internal_error', 'Something went wrong; see the server log.')
            : json(page([makeTrade()])),
      ],
    ])
    const user = userEvent.setup()
    renderWith(<HistoryPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('EURUSD')).toBeInTheDocument()
  })

  describe('with 600 trades (more than a screen can sensibly show)', () => {
    it('draws only one page of rows, never all 600', async () => {
      mockApi([GROUPS, tradesServer(600)])
      renderWith(<HistoryPage />)
      await screen.findByText('ASSET0')
      expect(dataRows()).toHaveLength(50)
      expect(screen.getByText('1–50 of 600')).toBeInTheDocument()
      expect(screen.getByText('Page 1 of 12')).toBeInTheDocument()
    })

    it('moves through the pages and asks the server for exactly that page', async () => {
      const api = mockApi([GROUPS, tradesServer(600)])
      const user = userEvent.setup()
      renderWith(<HistoryPage />)
      await screen.findByText('ASSET0')
      expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

      await user.click(screen.getByRole('button', { name: 'Next' }))
      expect(await screen.findByText('ASSET50')).toBeInTheDocument()
      expect(screen.queryByText('ASSET0')).not.toBeInTheDocument()
      expect(screen.getByText('51–100 of 600')).toBeInTheDocument()
      expect(api.calls.at(-1)?.path).toContain('offset=50')

      await user.click(screen.getByRole('button', { name: 'Previous' }))
      expect(await screen.findByText('ASSET0')).toBeInTheDocument()
    })

    it('can show 200 rows at a time, and the last page holds the remainder', async () => {
      mockApi([GROUPS, tradesServer(600)])
      const user = userEvent.setup()
      renderWith(<HistoryPage />)
      await screen.findByText('ASSET0')
      await user.selectOptions(screen.getByLabelText('Rows per page'), '200')
      await waitFor(() => {
        expect(dataRows()).toHaveLength(200)
      })
      await user.click(screen.getByRole('button', { name: 'Next' }))
      await user.click(await screen.findByRole('button', { name: 'Next' }))
      await screen.findByText('ASSET400')
      expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
      expect(screen.getByText('401–600 of 600')).toBeInTheDocument()
    })

    it('goes back to the first page when a filter changes', async () => {
      const api = mockApi([GROUPS, tradesServer(600)])
      const user = userEvent.setup()
      renderWith(<HistoryPage />)
      await screen.findByText('ASSET0')
      await user.click(screen.getByRole('button', { name: 'Next' }))
      await screen.findByText('ASSET50')
      await user.selectOptions(screen.getByLabelText('Result'), 'won')
      await waitFor(() => {
        expect(api.calls.at(-1)?.path).toMatch(/status=won/)
      })
      expect(api.calls.at(-1)?.path).toContain('offset=0')
    })
  })

  it('filters by group and account', async () => {
    const api = mockApi([GROUPS, tradesServer(2)])
    const user = userEvent.setup()
    renderWith(<HistoryPage />)
    await screen.findByText('ASSET0')
    await user.selectOptions(await screen.findByLabelText('Group'), 'Beta')
    await user.selectOptions(screen.getByLabelText('Account'), 'real')
    await waitFor(() => {
      expect(api.calls.at(-1)?.path).toMatch(/group_id=2/)
    })
    expect(api.calls.at(-1)?.path).toMatch(/account_type=real/)
  })
})
