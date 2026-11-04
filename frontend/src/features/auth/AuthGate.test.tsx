import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { apiError, json, mockApi } from '../../test/utils'
import { AuthGate } from './AuthGate'

afterEach(() => {
  vi.unstubAllGlobals()
})

const OWNER = { username: 'joseph', role: 'admin' }
const LOGGED_OUT = { setup_required: false, authenticated: false, user: null }
const FIRST_RUN = { setup_required: true, authenticated: false, user: null }
const LOGGED_IN = { setup_required: false, authenticated: true, user: OWNER }

/** Stands for the dashboard: asks the API for something, as every page does. */
function Dashboard() {
  const status = useQuery({ queryKey: ['status'], queryFn: ({ signal }) => api.health(signal) })
  return <p>the dashboard {status.isError ? '(failed)' : ''}</p>
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AuthGate>
        <Dashboard />
      </AuthGate>
    </QueryClientProvider>,
  )
  return { client, user: userEvent.setup() }
}

describe('who sees the dashboard', () => {
  it('shows it to a logged-in owner and to nobody else', async () => {
    mockApi([
      ['GET', '/auth/state', json(LOGGED_IN)],
      ['GET', '/health', json({})],
    ])
    setup()
    expect(await screen.findByText(/the dashboard/)).toBeVisible()
  })

  it('shows the login page, and not the dashboard, to a visitor', async () => {
    const api = mockApi([['GET', '/auth/state', json(LOGGED_OUT)]])
    setup()
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeVisible()
    expect(screen.queryByText(/the dashboard/)).not.toBeInTheDocument()
    expect(api.to('GET', '/health')).toHaveLength(0) // nothing was asked of the API
  })

  it('shows the first-run page when there is no account yet', async () => {
    mockApi([['GET', '/auth/state', json(FIRST_RUN)]])
    setup()
    expect(await screen.findByRole('heading', { name: 'Create the owner account' })).toBeVisible()
    expect(screen.getByLabelText('Setup code')).toBeVisible()
  })

  it('says so when the backend cannot be reached, and tries again on request', async () => {
    let answers = 0
    mockApi([
      [
        'GET',
        '/auth/state',
        () => (++answers === 1 ? new Error('network down') : json(LOGGED_OUT)),
      ],
    ])
    const { user } = setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the backend')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeVisible()
  })
})

describe('logging in', () => {
  it('sends the name without stray spaces and then shows the dashboard', async () => {
    let loggedIn = false
    const mock = mockApi([
      ['GET', '/auth/state', () => json(loggedIn ? LOGGED_IN : LOGGED_OUT)],
      [
        'POST',
        '/auth/login',
        () => {
          loggedIn = true
          return json(OWNER)
        },
      ],
      ['GET', '/health', json({})],
    ])
    const { user } = setup()
    await user.type(await screen.findByLabelText('Username'), '  joseph ')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText(/the dashboard/)).toBeVisible()
    expect(mock.to('POST', '/auth/login')[0]?.body).toEqual({
      username: 'joseph',
      password: 'correct horse battery',
    })
  })

  it('shows the server’s answer to a wrong password and stays on the login page', async () => {
    const mock = mockApi([
      ['GET', '/auth/state', json(LOGGED_OUT)],
      ['POST', '/auth/login', apiError(401, 'invalid_login', 'Wrong username or password.')],
    ])
    const { user } = setup()
    await user.type(await screen.findByLabelText('Username'), 'joseph')
    await user.type(screen.getByLabelText('Password'), 'not the password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.')
    expect(screen.getByRole('heading', { name: 'Log in' })).toBeVisible()
    expect(mock.to('GET', '/auth/state')).toHaveLength(1) // a wrong password is not a lost session
  })

  it('does not send an empty form', async () => {
    mockApi([['GET', '/auth/state', json(LOGGED_OUT)]])
    setup()
    expect(await screen.findByRole('button', { name: 'Log in' })).toBeDisabled()
  })

  it('tells the owner how to get back in after forgetting the password', async () => {
    mockApi([['GET', '/auth/state', json(LOGGED_OUT)]])
    setup()
    expect(await screen.findByText('npm run owner:reset')).toBeVisible()
  })
})

describe('a session that ends while the dashboard is open', () => {
  it('sends the owner back to the login page', async () => {
    let expired = false
    mockApi([
      ['GET', '/auth/state', () => json(expired ? LOGGED_OUT : LOGGED_IN)],
      [
        'GET',
        '/health',
        () => {
          expired = true
          return apiError(401, 'not_authenticated', 'Log in to continue.')
        },
      ],
    ])
    setup()
    expect(await screen.findByRole('heading', { name: 'Log in' })).toBeVisible()
    expect(screen.queryByText(/the dashboard/)).not.toBeInTheDocument()
  })
})

describe('first-run setup', () => {
  const fill = async (
    user: ReturnType<typeof userEvent.setup>,
    password = 'a long enough password',
    repeat = password,
  ) => {
    await user.type(await screen.findByLabelText('Setup code'), ' abcd-efgh-jkmn ')
    await user.type(screen.getByLabelText('Username'), 'joseph')
    await user.type(screen.getByLabelText('Password'), password)
    await user.type(screen.getByLabelText('Repeat the password'), repeat)
    await user.click(screen.getByRole('button', { name: 'Create the account' }))
  }

  it('creates the account and goes straight to the dashboard', async () => {
    let created = false
    const mock = mockApi([
      ['GET', '/auth/state', () => json(created ? LOGGED_IN : FIRST_RUN)],
      [
        'POST',
        '/auth/setup',
        () => {
          created = true
          return json(OWNER, 201)
        },
      ],
      ['GET', '/health', json({})],
    ])
    const { user } = setup()
    await fill(user)
    expect(await screen.findByText(/the dashboard/)).toBeVisible()
    expect(mock.to('POST', '/auth/setup')[0]?.body).toEqual({
      setup_code: 'abcd-efgh-jkmn',
      username: 'joseph',
      password: 'a long enough password',
    })
  })

  it('does not send two different passwords or a short one', async () => {
    const mock = mockApi([['GET', '/auth/state', json(FIRST_RUN)]])
    const { user } = setup()
    await fill(user, 'a long enough password', 'something else entirely')
    expect(await screen.findByRole('alert')).toHaveTextContent('not the same')
    await user.clear(screen.getByLabelText('Password'))
    await user.clear(screen.getByLabelText('Repeat the password'))
    await user.type(screen.getByLabelText('Password'), 'short')
    await user.type(screen.getByLabelText('Repeat the password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Create the account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 10')
    expect(mock.to('POST', '/auth/setup')).toHaveLength(0)
  })

  it('shows what the server says about a wrong code', async () => {
    mockApi([
      ['GET', '/auth/state', json(FIRST_RUN)],
      [
        'POST',
        '/auth/setup',
        apiError(
          403,
          'wrong_setup_code',
          "That setup code is not right. Look in the application's log.",
        ),
      ],
    ])
    const { user } = setup()
    await fill(user)
    expect(await screen.findByRole('alert')).toHaveTextContent('That setup code is not right')
  })
})
