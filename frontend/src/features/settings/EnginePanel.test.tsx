import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EngineInfo, Snapshot } from '../../api/types'
import { makeSnapshot } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import { engineInfo } from './engineFixtures'
import { telegramStatus } from './telegramFixtures'
import SettingsPage from './SettingsPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const SETTINGS = { items: [], apply_note: 'A saved setting is used from the next start.' }
const SECRETS = { key: 'ok', items: [] }

/** The Settings page against a backend whose engine answers come from `engine()`. */
function setup(
  engine: () => EngineInfo,
  extra: Parameters<typeof mockApi>[0] = [],
  account: Snapshot['account_type'] = 'demo',
) {
  const api = mockApi([
    ['GET', '/engine', () => json(engine())],
    ['GET', '/status', json(makeSnapshot({ account_type: account }))],
    ['GET', '/settings', json(SETTINGS)],
    ['GET', '/secrets', json(SECRETS)],
    ['GET', '/telegram/login', json(telegramStatus())],
    ...extra,
  ])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  )
  return { api, user: userEvent.setup() }
}

describe('starting and stopping the engine', () => {
  it('says it is stopped and starts it', async () => {
    let current = engineInfo()
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/engine/start',
          () => {
            current = engineInfo({ state: 'running', desired: true })
            return json(current)
          },
        ],
      ],
    )
    expect(await screen.findByText('Stopped')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Start the engine' }))
    expect(await screen.findByText('Running')).toBeVisible()
    expect(api.to('POST', '/engine/start')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Stop the engine' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Start the engine' })).toBeNull()
  })

  it('will not offer to start while a login is missing, and says which', async () => {
    setup(() =>
      engineInfo({
        missing_logins: ['Quotex password'],
        logins: [{ label: 'Quotex password', present: false, source: 'missing' }],
      }),
    )
    expect(await screen.findByRole('button', { name: 'Start the engine' })).toBeDisabled()
    expect(screen.getByText(/Before it can start, add: Quotex password/)).toBeVisible()
    expect(screen.getByText('missing')).toBeVisible()
  })

  it('shows why the last start failed and lets the owner try again', async () => {
    let current = engineInfo({ state: 'failed', error: 'Quotex refused the login.' })
    const { user } = setup(
      () => current,
      [
        [
          'POST',
          '/engine/start',
          () => {
            current = engineInfo({ state: 'running' })
            return json(current)
          },
        ],
      ],
    )
    expect(await screen.findByText('Quotex refused the login.')).toBeVisible()
    expect(screen.getByText('Could not start')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Start the engine' }))
    expect(await screen.findByText('Running')).toBeVisible()
    expect(screen.queryByText('Quotex refused the login.')).toBeNull()
  })

  it('shows the server’s reason when a start is refused', async () => {
    const { user } = setup(
      () => engineInfo(),
      [
        [
          'POST',
          '/engine/start',
          apiError(409, 'engine_start_failed', 'The stored Quotex email cannot be used.'),
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Start the engine' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('stored Quotex email cannot be used')
  })

  it('asks before stopping, and says what happens to open trades', async () => {
    let current = engineInfo({ state: 'running' })
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/engine/stop',
          () => {
            current = engineInfo()
            return json(current)
          },
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Stop the engine' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('unknown')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.to('POST', '/engine/stop')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Stop the engine' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stop it' }))
    expect(await screen.findByText('Stopped')).toBeVisible()
  })

  it('restarts without asking', async () => {
    const { api, user } = setup(
      () => engineInfo({ state: 'running' }),
      [['POST', '/engine/restart', json(engineInfo({ state: 'running' }))]],
    )
    await user.click(await screen.findByRole('button', { name: 'Restart' }))
    await vi.waitFor(() => {
      expect(api.to('POST', '/engine/restart')).toHaveLength(1)
    })
  })

  it('says the engine always starts on the demo account', async () => {
    setup(() => engineInfo())
    expect(await screen.findByText(/always starts on the/)).toHaveTextContent('demo')
  })
})

describe('real money', () => {
  it('is not allowed by default and needs the password to allow', async () => {
    let current = engineInfo({ state: 'running' })
    const { api, user } = setup(
      () => current,
      [
        [
          'PUT',
          '/account/real-trading',
          () => {
            current = engineInfo({ state: 'running', real_trading_allowed: true })
            return json({ account_type: 'demo', real_trading_allowed: true })
          },
        ],
      ],
    )
    expect(await screen.findByText('Not allowed')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Switch to the REAL account/ })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Allow real-money trading…' }))
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('Your password'), 'correct horse battery')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(await screen.findByText('Allowed')).toBeVisible()
    expect(api.to('PUT', '/account/real-trading')[0]?.body).toEqual({
      allowed: true,
      password: 'correct horse battery',
    })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('does not send an empty password and shows a wrong one', async () => {
    const { api, user } = setup(
      () => engineInfo({ state: 'running' }),
      [
        [
          'PUT',
          '/account/real-trading',
          apiError(401, 'invalid_login', 'The password is not right.'),
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Allow real-money trading…' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(api.to('PUT', '/account/real-trading')).toHaveLength(0)
    await user.type(within(dialog).getByLabelText('Your password'), 'wrong wrong')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The password is not right.')
  })

  it('switches to the real account only with the password, and only when allowed and running', async () => {
    const { api, user } = setup(
      () => engineInfo({ state: 'running', real_trading_allowed: true }),
      [['PUT', '/account', json({ account_type: 'real', real_trading_allowed: true })]],
    )
    await user.click(await screen.findByRole('button', { name: 'Switch to the REAL account…' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('REAL money')
    await user.type(within(dialog).getByLabelText('Your password'), 'correct horse battery')
    await user.click(within(dialog).getByRole('button', { name: 'Switch to REAL' }))
    await vi.waitFor(() => {
      expect(api.to('PUT', '/account')[0]?.body).toEqual({
        account_type: 'real',
        password: 'correct horse battery',
      })
    })
  })

  it('cannot switch to the real account while the engine is stopped', async () => {
    setup(() => engineInfo({ state: 'stopped', real_trading_allowed: true }))
    expect(
      await screen.findByRole('button', { name: 'Switch to the REAL account…' }),
    ).toBeDisabled()
  })

  it('goes back to demo with no password', async () => {
    const { api, user } = setup(
      () => engineInfo({ state: 'running', real_trading_allowed: true }),
      [['PUT', '/account', json({ account_type: 'demo', real_trading_allowed: true })]],
      'real',
    )
    await user.click(await screen.findByRole('button', { name: 'Switch back to the demo account' }))
    await vi.waitFor(() => {
      expect(api.to('PUT', '/account')[0]?.body).toEqual({ account_type: 'demo' })
    })
  })

  it('shows why the permission cannot be taken back while real is in use', async () => {
    const { user } = setup(
      () => engineInfo({ state: 'running', real_trading_allowed: true }),
      [
        [
          'PUT',
          '/account/real-trading',
          apiError(409, 'real_trading_in_use', 'The REAL account is in use. Switch back first.'),
        ],
      ],
      'real',
    )
    await user.click(
      await screen.findByRole('button', { name: 'Stop allowing real-money trading…' }),
    )
    const dialog = screen.getByRole('dialog')
    await user.type(within(dialog).getByLabelText('Your password'), 'correct horse battery')
    await user.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Switch back first.')
  })

  it('never keeps the password on the page after the dialog closes', async () => {
    const { user } = setup(
      () => engineInfo({ state: 'running' }),
      [
        [
          'PUT',
          '/account/real-trading',
          json({ account_type: 'demo', real_trading_allowed: true }),
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Allow real-money trading…' }))
    await user.type(screen.getByLabelText('Your password'), 'secret-one-two')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(document.body.textContent).not.toContain('secret-one-two')
    await user.click(screen.getByRole('button', { name: 'Allow real-money trading…' }))
    expect(screen.getByLabelText('Your password')).toHaveValue('')
  })
})
