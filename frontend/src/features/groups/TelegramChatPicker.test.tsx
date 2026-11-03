import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TelegramChat } from '../../api/types'
import { makeGroup } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import GroupFormPage from './GroupFormPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const CHATS: TelegramChat[] = [
  { chat_id: -1001, title: 'Alpha Signals', kind: 'group', added: false },
  { chat_id: -1002, title: 'Zebra VIP', kind: 'channel', added: false },
  { chat_id: -1003, title: 'Already Here', kind: 'group', added: true },
]

function setup(path = '/groups/new') {
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

const open = (user: ReturnType<typeof userEvent.setup>) =>
  user.click(screen.getByRole('button', { name: 'Choose from my Telegram chats' }))

describe('choosing a Telegram chat when adding a group', () => {
  it('does not talk to Telegram until the button is pressed', () => {
    const api = mockApi([]) // any request at all would fail the test
    setup()
    expect(screen.getByRole('button', { name: 'Choose from my Telegram chats' })).toBeVisible()
    expect(api.calls).toHaveLength(0)
  })

  it('shows the chats by name and fills in the id and the name of the one picked', async () => {
    const api = mockApi([
      ['GET', '/telegram/chats', json({ items: CHATS })],
      ['POST', '/groups', json(makeGroup(), 201)],
      ['GET', '/groups', json({ items: [], total: 0, limit: 50, offset: 0 })],
    ])
    const user = setup()
    await open(user)
    expect(await screen.findByRole('button', { name: /Alpha Signals/ })).toBeVisible()
    expect(screen.getByRole('button', { name: /Zebra VIP/ })).toHaveTextContent('channel')

    await user.click(screen.getByRole('button', { name: /Alpha Signals/ }))

    expect(screen.getByLabelText('Telegram chat id')).toHaveValue('-1001')
    expect(screen.getByLabelText('Name')).toHaveValue('Alpha Signals')
    expect(screen.queryByRole('group', { name: 'Your Telegram chats' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Create group' }))
    expect(await screen.findByText('the groups list')).toBeInTheDocument()
    const sent = api.to('POST', '/groups')[0]?.body as { telegram_chat_id: number; title: string }
    expect(sent.telegram_chat_id).toBe(-1001)
    expect(sent.title).toBe('Alpha Signals')
  })

  it('keeps a name the owner already typed', async () => {
    mockApi([['GET', '/telegram/chats', json({ items: CHATS })]])
    const user = setup()
    await user.type(screen.getByLabelText('Name'), 'My own label')
    await open(user)
    await user.click(await screen.findByRole('button', { name: /Zebra VIP/ }))
    expect(screen.getByLabelText('Name')).toHaveValue('My own label')
    expect(screen.getByLabelText('Telegram chat id')).toHaveValue('-1002')
  })

  it('does not let a chat that already has a group be picked again', async () => {
    mockApi([['GET', '/telegram/chats', json({ items: CHATS })]])
    const user = setup()
    await open(user)
    const taken = await screen.findByRole('button', { name: /Already Here/ })
    expect(taken).toBeDisabled()
    expect(taken).toHaveTextContent('already added')
  })

  it('narrows the list as the owner searches, ignoring capital letters', async () => {
    mockApi([['GET', '/telegram/chats', json({ items: CHATS })]])
    const user = setup()
    await open(user)
    await screen.findByRole('button', { name: /Alpha Signals/ })
    await user.type(screen.getByLabelText('Search your chats'), 'zEBRA')
    expect(screen.queryByRole('button', { name: /Alpha Signals/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Zebra VIP/ })).toBeVisible()
    await user.clear(screen.getByLabelText('Search your chats'))
    await user.type(screen.getByLabelText('Search your chats'), 'nothing like it')
    expect(screen.getByText('No chat matches that.')).toBeVisible()
  })

  it('explains an unavailable list and leaves typing the id possible', async () => {
    mockApi([
      [
        'GET',
        '/telegram/chats',
        apiError(
          503,
          'engine_not_running',
          'The trading engine is not running. Set ENGINE_ENABLED=true in backend/.env.',
        ),
      ],
    ])
    const user = setup()
    await open(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('Set ENGINE_ENABLED=true')
    expect(screen.getByText('You can still type the chat id below.')).toBeVisible()
    await user.type(screen.getByLabelText('Telegram chat id'), '-1001234567890')
    expect(screen.getByLabelText('Telegram chat id')).toHaveValue('-1001234567890')
  })

  it('asks again when "Try again" is pressed', async () => {
    let answers = 0
    const api = mockApi([
      [
        'GET',
        '/telegram/chats',
        () =>
          ++answers === 1
            ? apiError(503, 'telegram_not_connected', 'Telegram is not connected yet.')
            : json({ items: CHATS }),
      ],
    ])
    const user = setup()
    await open(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('Telegram is not connected yet.')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('button', { name: /Alpha Signals/ })).toBeVisible()
    expect(api.to('GET', '/telegram/chats')).toHaveLength(2)
  })

  it('says so when the account is in no group or channel', async () => {
    mockApi([['GET', '/telegram/chats', json({ items: [] })]])
    const user = setup()
    await open(user)
    expect(await screen.findByText(/not in any group or channel/)).toBeVisible()
  })

  it('can be closed without choosing, and asks again when reopened', async () => {
    const api = mockApi([['GET', '/telegram/chats', json({ items: CHATS })]])
    const user = setup()
    await open(user)
    await screen.findByRole('button', { name: /Alpha Signals/ })
    await user.click(screen.getByRole('button', { name: 'Close the list' }))
    expect(screen.getByLabelText('Telegram chat id')).toHaveValue('')
    await open(user)
    await screen.findByRole('button', { name: /Alpha Signals/ })
    expect(api.to('GET', '/telegram/chats')).toHaveLength(2) // a fresh list each time
  })
})

describe('editing a group', () => {
  it('has no chat picker: the chat of a group cannot change', async () => {
    mockApi([['GET', '/groups/7', json(makeGroup({ id: 7 }))]])
    setup('/groups/7/edit')
    expect(await screen.findByLabelText('Telegram chat id')).toHaveAttribute('readonly')
    expect(
      screen.queryByRole('button', { name: 'Choose from my Telegram chats' }),
    ).not.toBeInTheDocument()
  })
})
