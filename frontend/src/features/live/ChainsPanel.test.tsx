import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../../api/queries'
import { makeChain, makeGroup, makeSnapshot, page } from '../../test/fixtures'
import { apiError, json, mockApi, renderWith, testClient } from '../../test/utils'
import { ChainsPanel } from './ChainsPanel'

afterEach(() => {
  vi.unstubAllGlobals()
})

const GROUPS = ['GET', '/groups', json(page([makeGroup({ title: 'Alpha signals' })]))] as const
const chain = makeChain({ id: 'abc', step: 1, consecutive_losses: 1, max_steps: 3 })

function setup(routes: Parameters<typeof mockApi>[0] = []) {
  const api = mockApi([GROUPS, ...routes])
  const client = testClient()
  client.setQueryData(keys.groups, page([makeGroup({ title: 'Alpha signals' })]))
  return {
    api,
    user: userEvent.setup(),
    ...renderWith(<ChainsPanel chains={[chain]} />, { client }),
  }
}

describe('ChainsPanel', () => {
  it('says so when nothing is running', () => {
    mockApi([])
    renderWith(<ChainsPanel chains={[]} />)
    expect(screen.getByText(/No chains are running/)).toBeInTheDocument()
  })

  it('shows each chain with its group, asset, direction and step progress', () => {
    setup()
    const row = screen.getByRole('row', { name: /EURUSD/ })
    expect(within(row).getByText('Alpha signals')).toBeInTheDocument()
    expect(within(row).getByText('CALL')).toBeInTheDocument()
    expect(within(row).getByText('Martingale')).toBeInTheDocument()
    expect(within(row).getByText('Step 2 of 4')).toBeInTheDocument() // original + 3 follow-ups
    expect(within(row).getByRole('progressbar', { name: 'Step 2 of 4' })).toHaveAttribute(
      'value',
      '2',
    )
  })

  describe('skip to base', () => {
    it('asks first, says what it does and to which account, and sends nothing on cancel', async () => {
      const { api, user } = setup()
      await user.click(screen.getByRole('button', { name: 'Skip to base: EURUSD' }))
      const dialog = screen.getByRole('dialog', { name: 'Skip to base?' })
      expect(dialog).toHaveTextContent('Alpha signals')
      expect(dialog).toHaveTextContent('DEMO')
      expect(dialog).toHaveTextContent('base stake of 1.00')
      expect(api.to('POST', '/chains/abc/end')).toHaveLength(0)

      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(api.to('POST', '/chains/abc/end')).toHaveLength(0)
    })

    it('ends the chain only after the owner confirms', async () => {
      const { api, user } = setup([
        [
          'POST',
          '/chains/abc/end',
          json({ chain: { ...chain, status: 'stopped' }, stop_requested: false }),
        ],
      ])
      await user.click(screen.getByRole('button', { name: 'Skip to base: EURUSD' }))
      await user.click(screen.getByRole('button', { name: 'Skip to base' }))
      await waitFor(() => {
        expect(api.to('POST', '/chains/abc/end')).toHaveLength(1)
      })
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      })
    })

    it('shows the server’s reason and stays open when it cannot', async () => {
      const { user } = setup([
        [
          'POST',
          '/chains/abc/end',
          apiError(409, 'chain_not_running', 'the chain ended as completed'),
        ],
      ])
      await user.click(screen.getByRole('button', { name: 'Skip to base: EURUSD' }))
      await user.click(screen.getByRole('button', { name: 'Skip to base' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('the chain ended as completed')
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
  })

  describe('stop after current', () => {
    it('is sent at once and then the chain is marked as stopping', async () => {
      const { api, user } = setup([
        ['POST', '/chains/abc/stop-after-current', json({ chain, stop_requested: true })],
      ])
      await user.click(screen.getByRole('button', { name: 'Stop after current trade: EURUSD' }))
      expect(await screen.findByText('stops after this trade')).toBeInTheDocument()
      expect(api.to('POST', '/chains/abc/stop-after-current')).toHaveLength(1)
      expect(
        screen.getByRole('button', { name: 'Stop after current trade: EURUSD' }),
      ).toBeDisabled()
    })

    it('shows why it failed', async () => {
      const { user } = setup([
        [
          'POST',
          '/chains/abc/stop-after-current',
          apiError(503, 'engine_not_running', 'The trading engine is not running.'),
        ],
      ])
      await user.click(screen.getByRole('button', { name: 'Stop after current trade: EURUSD' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('not running')
      expect(screen.queryByText('stops after this trade')).not.toBeInTheDocument()
    })
  })

  it('names the account it is about to act on even when the chain was started on another', async () => {
    mockApi([GROUPS])
    const client = testClient(makeSnapshot({ account_type: 'real' }))
    const user = userEvent.setup()
    renderWith(<ChainsPanel chains={[chain]} />, { client })
    await user.click(screen.getByRole('button', { name: 'Skip to base: EURUSD' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('REAL')
  })
})
