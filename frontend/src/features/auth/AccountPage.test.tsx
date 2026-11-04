import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { keys } from '../../api/queries'
import { apiError, mockApi } from '../../test/utils'
import AccountPage from './AccountPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const LOGGED_IN = {
  setup_required: false,
  authenticated: true,
  user: { username: 'joseph', role: 'admin' },
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(keys.auth, LOGGED_IN)
  render(
    <QueryClientProvider client={client}>
      <AccountPage />
    </QueryClientProvider>,
  )
  return { client, user: userEvent.setup() }
}

async function fill(user: ReturnType<typeof userEvent.setup>, next = 'a different long password') {
  await user.type(screen.getByLabelText('Current password'), 'the old password')
  await user.type(screen.getByLabelText('New password'), next)
  await user.type(screen.getByLabelText('Repeat the new password'), next)
  await user.click(screen.getByRole('button', { name: 'Change the password' }))
}

describe('the account page', () => {
  it('says who is logged in', () => {
    mockApi([])
    setup()
    expect(screen.getByText('joseph')).toBeVisible()
  })

  it('changes the password and says the other browsers were logged out', async () => {
    const mock = mockApi([['POST', '/auth/password', new Response(null, { status: 204 })]])
    const { user } = setup()
    await fill(user)
    expect(await screen.findByRole('status')).toHaveTextContent('other browser')
    expect(mock.to('POST', '/auth/password')[0]?.body).toEqual({
      current_password: 'the old password',
      new_password: 'a different long password',
    })
    expect(screen.getByLabelText('Current password')).toHaveValue('') // not left on screen
  })

  it('shows the server’s answer when the current password is wrong', async () => {
    mockApi([
      [
        'POST',
        '/auth/password',
        apiError(401, 'invalid_login', 'The current password is not right.'),
      ],
    ])
    const { user } = setup()
    await fill(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('The current password is not right.')
  })

  it('does not send a short or mismatched new password', async () => {
    const mock = mockApi([])
    const { user } = setup()
    await fill(user, 'short')
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 10')
    expect(mock.calls).toHaveLength(0)
  })

  it('logs out: tells the server, forgets what was fetched and shows logged-out state', async () => {
    const mock = mockApi([['POST', '/auth/logout', new Response(null, { status: 204 })]])
    const { client, user } = setup()
    client.setQueryData(['groups'], { items: [] })
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    await vi.waitFor(() => {
      expect(mock.to('POST', '/auth/logout')).toHaveLength(1)
      expect(client.getQueryData(['groups'])).toBeUndefined()
      expect(client.getQueryData(keys.auth)).toEqual({
        setup_required: false,
        authenticated: false,
        user: null,
      })
    })
  })
})

describe('logging out when the server cannot be reached', () => {
  it('still forgets everything in this browser', async () => {
    mockApi([['POST', '/auth/logout', new Error('offline')]])
    const { client, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    await vi.waitFor(() => {
      expect(client.getQueryData(keys.auth)).toMatchObject({ authenticated: false })
    })
  })
})
