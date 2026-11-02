import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeGroup, page } from '../../test/fixtures'
import { apiError, json, mockApi, renderWith } from '../../test/utils'
import GroupsPage from './GroupsPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const alpha = makeGroup({ active_chains: 2 })
const beta = makeGroup({
  id: 2,
  title: 'Beta',
  telegram_chat_id: -1002,
  enabled: false,
  paused: true,
  settings: {
    ...(makeGroup().settings ?? ({} as never)),
    strategy: 'no_martingale',
    max_steps: 0,
    multipliers: [],
  },
})

describe('GroupsPage', () => {
  it('lists the groups with their strategy, stake, steps and state', async () => {
    mockApi([['GET', '/groups', json(page([alpha, beta]))]])
    renderWith(<GroupsPage />)
    const first = (await screen.findByText('Alpha signals')).closest('tr') as HTMLElement
    expect(within(first).getByText('Martingale')).toBeInTheDocument()
    expect(within(first).getByText('1.00')).toBeInTheDocument()
    expect(within(first).getByText('3 × (2.0, 2.5, 3.0)')).toBeInTheDocument()
    expect(within(first).getByText('80%')).toBeInTheDocument()
    expect(within(first).getByText('Enabled')).toBeInTheDocument()
    expect(within(first).getByText('2')).toBeInTheDocument() // chains running
    const second = screen.getByText('Beta').closest('tr') as HTMLElement
    expect(within(second).getByText('Disabled')).toBeInTheDocument()
    expect(within(second).getByText('Paused')).toBeInTheDocument()
    expect(within(second).getByText('none')).toBeInTheDocument()
  })

  it('invites the owner to add the first group', async () => {
    mockApi([['GET', '/groups', json(page([]))]])
    renderWith(<GroupsPage />)
    expect(await screen.findByText(/No groups yet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add a group' })).toHaveAttribute('href', '/groups/new')
  })

  it('shows a failure to load, with a way to retry', async () => {
    mockApi([['GET', '/groups', apiError(500, 'internal_error', 'Something went wrong')]])
    renderWith(<GroupsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('links each group to its edit form', async () => {
    mockApi([['GET', '/groups', json(page([alpha]))]])
    renderWith(<GroupsPage />)
    const link = await screen.findByRole('link', { name: 'Edit Alpha signals' })
    expect(link).toHaveAttribute('href', '/groups/1/edit')
  })

  it('disables an enabled group by saving it again with the flag off', async () => {
    const api = mockApi([
      ['GET', '/groups', json(page([alpha]))],
      ['PUT', '/groups/1', json({ ...alpha, enabled: false })],
    ])
    const user = userEvent.setup()
    renderWith(<GroupsPage />)
    await user.click(await screen.findByRole('button', { name: 'Disable Alpha signals' }))
    await waitFor(() => {
      expect(api.to('PUT', '/groups/1')).toHaveLength(1)
    })
    expect(api.to('PUT', '/groups/1')[0]?.body).toMatchObject({
      title: 'Alpha signals',
      enabled: false,
      settings: { strategy: 'martingale', base_stake: '1.00', multipliers: ['2.0', '2.5', '3.0'] },
    })
  })

  it('enables a disabled group', async () => {
    const api = mockApi([
      ['GET', '/groups', json(page([beta]))],
      ['PUT', '/groups/2', json({ ...beta, enabled: true })],
    ])
    const user = userEvent.setup()
    renderWith(<GroupsPage />)
    await user.click(await screen.findByRole('button', { name: 'Enable Beta' }))
    await waitFor(() => {
      expect(api.to('PUT', '/groups/2')[0]?.body).toMatchObject({ enabled: true })
    })
  })

  it('pauses and resumes', async () => {
    const api = mockApi([
      ['GET', '/groups', json(page([alpha, beta]))],
      ['POST', '/groups/1/pause', json({ ...alpha, paused: true })],
      ['POST', '/groups/2/resume', json({ ...beta, paused: false })],
    ])
    const user = userEvent.setup()
    renderWith(<GroupsPage />)
    await user.click(await screen.findByRole('button', { name: 'Pause Alpha signals' }))
    await user.click(screen.getByRole('button', { name: 'Resume Beta' }))
    await waitFor(() => {
      expect(api.to('POST', '/groups/1/pause')).toHaveLength(1)
      expect(api.to('POST', '/groups/2/resume')).toHaveLength(1)
    })
  })

  it('shows why a pause failed, next to the group it was for', async () => {
    mockApi([
      ['GET', '/groups', json(page([alpha]))],
      [
        'POST',
        '/groups/1/pause',
        apiError(503, 'engine_not_running', 'The trading engine is not running.'),
      ],
    ])
    const user = userEvent.setup()
    renderWith(<GroupsPage />)
    await user.click(await screen.findByRole('button', { name: 'Pause Alpha signals' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Alpha signals: The trading engine is not running.',
    )
  })

  describe('delete', () => {
    it('asks first, and sends nothing when cancelled', async () => {
      const api = mockApi([['GET', '/groups', json(page([alpha]))]])
      const user = userEvent.setup()
      renderWith(<GroupsPage />)
      await user.click(await screen.findByRole('button', { name: 'Delete Alpha signals' }))
      const dialog = screen.getByRole('dialog', { name: 'Delete this group?' })
      expect(dialog).toHaveTextContent('Alpha signals')
      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(api.to('DELETE', '/groups/1')).toHaveLength(0)
    })

    it('deletes after confirmation', async () => {
      const api = mockApi([
        ['GET', '/groups', json(page([alpha]))],
        ['DELETE', '/groups/1', new Response(null, { status: 204 })],
      ])
      const user = userEvent.setup()
      renderWith(<GroupsPage />)
      await user.click(await screen.findByRole('button', { name: 'Delete Alpha signals' }))
      await user.click(screen.getByRole('button', { name: 'Delete group' }))
      await waitFor(() => {
        expect(api.to('DELETE', '/groups/1')).toHaveLength(1)
      })
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      })
    })

    it('explains when a group with history cannot be deleted', async () => {
      mockApi([
        ['GET', '/groups', json(page([alpha]))],
        [
          'DELETE',
          '/groups/1',
          apiError(409, 'group_in_use', 'the group has history: disable it instead'),
        ],
      ])
      const user = userEvent.setup()
      renderWith(<GroupsPage />)
      await user.click(await screen.findByRole('button', { name: 'Delete Alpha signals' }))
      await user.click(screen.getByRole('button', { name: 'Delete group' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('disable it instead')
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
  })
})
