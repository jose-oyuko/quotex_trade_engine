import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeGroup, page } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import GroupFormPage from './GroupFormPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

function setup(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/groups/new" element={<GroupFormPage />} />
          <Route path="/groups/:id/edit" element={<GroupFormPage />} />
          <Route path="/groups" element={<p>the groups list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('adding a group', () => {
  it('sends the new group to the server and goes back to the list', async () => {
    const api = mockApi([
      ['POST', '/groups', json(makeGroup(), 201)],
      ['GET', '/groups', json(page([makeGroup()]))],
    ])
    const user = setup('/groups/new')
    await user.type(screen.getByLabelText('Name'), 'Alpha signals')
    await user.type(screen.getByLabelText('Telegram chat id'), '-1001234567890')
    await user.click(screen.getByRole('button', { name: 'Create group' }))

    expect(await screen.findByText('the groups list')).toBeInTheDocument()
    expect(api.to('POST', '/groups')).toHaveLength(1)
    expect(api.to('POST', '/groups')[0]?.body).toEqual({
      telegram_chat_id: -1001234567890,
      title: 'Alpha signals',
      enabled: true,
      settings: {
        parser: 'legacy_v1',
        asset_suffix_mode: 'otc',
        timezone: 'UTC-3',
        strategy: 'martingale',
        base_stake: '1.00',
        max_steps: 3,
        multipliers: ['2.0', '2.5', '3.0'],
        min_payout_pct: 80,
      },
    })
  })

  it('stays on the form and marks the chat id when that chat already has a group', async () => {
    mockApi([
      ['POST', '/groups', apiError(409, 'group_exists', 'a group for chat -1001 already exists')],
    ])
    const user = setup('/groups/new')
    await user.type(screen.getByLabelText('Name'), 'Alpha')
    await user.type(screen.getByLabelText('Telegram chat id'), '-1001')
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByText('a group for chat -1001 already exists')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Add a group' })).toBeInTheDocument()
  })

  it('shows what the server rejects on the field it concerns', async () => {
    mockApi([
      [
        'POST',
        '/groups',
        apiError(422, 'invalid_group', 'Mars/Base is not a UTC offset like UTC-3'),
      ],
    ])
    const user = setup('/groups/new')
    await user.type(screen.getByLabelText('Name'), 'Alpha')
    await user.type(screen.getByLabelText('Telegram chat id'), '-1001')
    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Mars/Base is not a UTC offset')
  })

  it('goes back to the list on cancel', async () => {
    const api = mockApi([])
    const user = setup('/groups/new')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(await screen.findByText('the groups list')).toBeInTheDocument()
    expect(api.calls).toEqual([])
  })
})

describe('editing a group', () => {
  it('shows the group’s settings, one multiplier per step, and saves changes', async () => {
    const api = mockApi([
      ['GET', '/groups/1', json(makeGroup())],
      ['PUT', '/groups/1', json(makeGroup({ title: 'Renamed' }))],
      ['GET', '/groups', json(page([makeGroup()]))],
    ])
    const user = setup('/groups/1/edit')
    const name = await screen.findByLabelText('Name')
    expect(name).toHaveValue('Alpha signals')
    expect(screen.getByLabelText('Base stake')).toHaveValue('1.00')
    expect(screen.getByLabelText('Multiplier for step 3')).toHaveValue('3.0')
    expect(screen.getByLabelText('Telegram chat id')).toHaveAttribute('readonly')

    await user.clear(name)
    await user.type(name, 'Renamed')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('the groups list')).toBeInTheDocument()
    const sent = api.to('PUT', '/groups/1')[0]?.body as Record<string, unknown>
    expect(sent).toMatchObject({ title: 'Renamed', enabled: true })
    expect(sent).not.toHaveProperty('telegram_chat_id')
  })

  it('says when the group does not exist', async () => {
    mockApi([['GET', '/groups/9', apiError(404, 'group_not_found', 'no group 9')]])
    setup('/groups/9/edit')
    expect(await screen.findByRole('alert')).toHaveTextContent('no group 9')
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
  })

  it('refuses an address that is not a group number', () => {
    mockApi([])
    setup('/groups/abc/edit')
    expect(screen.getByRole('alert')).toHaveTextContent('not a group')
  })

  it('does not lose the form if saving fails', async () => {
    mockApi([
      ['GET', '/groups/1', json(makeGroup())],
      ['PUT', '/groups/1', apiError(503, 'unavailable', 'The application is still starting.')],
    ])
    const user = setup('/groups/1/edit')
    await screen.findByLabelText('Name')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('still starting')
    })
    expect(screen.getByLabelText('Name')).toHaveValue('Alpha signals')
  })
})
