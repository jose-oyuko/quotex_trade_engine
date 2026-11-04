import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { QuotexLoginStatus } from '../../api/types'
import { makeSnapshot } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import { engineInfo } from './engineFixtures'
import { quotexStatus } from './quotexFixtures'
import SettingsPage from './SettingsPage'
import { telegramStatus } from './telegramFixtures'

afterEach(() => {
  vi.unstubAllGlobals()
})

const SETTINGS = { items: [], apply_note: 'A saved setting is used from the next start.' }
const SECRETS = { key: 'ok', items: [] }

function setup(login: () => QuotexLoginStatus, extra: Parameters<typeof mockApi>[0] = []) {
  const api = mockApi([
    ['GET', '/quotex/login', () => json(login())],
    ['GET', '/telegram/login', json(telegramStatus())],
    ['GET', '/engine', json(engineInfo())],
    ['GET', '/status', json(makeSnapshot())],
    ['GET', '/settings', json(SETTINGS)],
    ['GET', '/secrets', json(SECRETS)],
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

describe('logging in to Quotex', () => {
  it('needs the email and password stored first, and says so', async () => {
    setup(() => quotexStatus({ configured: false }))
    expect(await screen.findByRole('button', { name: 'Log in to Quotex' })).toBeDisabled()
    expect(screen.getByText(/Store your Quotex email and password above first/)).toBeVisible()
  })

  it('logs in with one button when Quotex asks for no PIN', async () => {
    let current = quotexStatus()
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/quotex/login/start',
          () => {
            current = quotexStatus({ state: 'logged_in' })
            return json(current)
          },
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Log in to Quotex' }))
    expect(await screen.findByText('Logged in')).toBeVisible()
    expect(api.to('POST', '/quotex/login/start')).toHaveLength(1)
    expect(api.to('POST', '/quotex/login/start')[0]?.body).toBeUndefined() // nothing is typed here
  })

  it('asks for the PIN in Quotex’s words and finishes with it', async () => {
    let current = quotexStatus()
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/quotex/login/start',
          () => {
            current = quotexStatus({
              state: 'pin_needed',
              pin_prompt: 'Enter the PIN we just sent to your email',
            })
            return json(current)
          },
        ],
        [
          'POST',
          '/quotex/login/pin',
          () => {
            current = quotexStatus({ state: 'logged_in' })
            return json(current)
          },
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Log in to Quotex' }))
    expect(await screen.findByText(/Enter the PIN we just sent to your email/)).toBeVisible()
    await user.type(screen.getByLabelText('PIN from the e-mail'), '123456')
    await user.click(screen.getByRole('button', { name: 'Send the PIN' }))
    expect(await screen.findByText('Logged in')).toBeVisible()
    expect(api.to('POST', '/quotex/login/pin')[0]?.body).toEqual({ pin: '123456' })
    expect(screen.queryByLabelText('PIN from the e-mail')).toBeNull()
  })

  it('shows the PIN box again after a page reload', async () => {
    setup(() =>
      quotexStatus({ state: 'pin_needed', pin_prompt: 'Enter the PIN we just sent to your email' }),
    )
    expect(await screen.findByLabelText('PIN from the e-mail')).toBeVisible()
  })

  it('does not send an empty PIN and shows the server’s reason for a bad one', async () => {
    const { api, user } = setup(
      () => quotexStatus({ state: 'pin_needed', pin_prompt: 'Enter the PIN' }),
      [
        [
          'POST',
          '/quotex/login/pin',
          apiError(
            422,
            'quotex_pin_invalid',
            'The PIN is digits only. Check the e-mail from Quotex.',
          ),
        ],
      ],
    )
    expect(await screen.findByRole('button', { name: 'Send the PIN' })).toBeDisabled()
    await user.type(screen.getByLabelText('PIN from the e-mail'), 'abc')
    await user.click(screen.getByRole('button', { name: 'Send the PIN' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('digits only')
    expect(api.to('POST', '/quotex/login/pin')).toHaveLength(1)
  })

  it('shows why a login was refused, in words', async () => {
    setup(() =>
      quotexStatus({
        message:
          "Quotex's website refused the request before the login. This is not a wrong password: Quotex sits behind Cloudflare.",
      }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('not a wrong password')
    expect(screen.getByRole('button', { name: 'Log in to Quotex' })).toBeEnabled() // try again
  })

  it('shows the server’s reason when it cannot even start', async () => {
    const { user } = setup(
      () => quotexStatus(),
      [
        [
          'POST',
          '/quotex/login/start',
          apiError(409, 'engine_running', 'Stop the trading engine first.'),
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Log in to Quotex' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Stop the trading engine first.')
  })

  it('waits while the application talks to Quotex, and can be cancelled', async () => {
    let current = quotexStatus({ state: 'working' })
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/quotex/login/cancel',
          () => {
            current = quotexStatus()
            return json(current)
          },
        ],
      ],
    )
    expect(await screen.findByText('Talking to Quotex…')).toBeVisible()
    await user.click(
      within(screen.getByText('Talking to Quotex…').closest('fieldset') as HTMLElement).getByRole(
        'button',
        { name: 'Cancel' },
      ),
    )
    expect(await screen.findByRole('button', { name: 'Log in to Quotex' })).toBeVisible()
    expect(api.to('POST', '/quotex/login/cancel')).toHaveLength(1)
  })

  it('cannot log in while the engine runs', async () => {
    setup(() => quotexStatus({ engine_running: true }))
    expect(await screen.findByRole('button', { name: 'Log in to Quotex' })).toBeDisabled()
    expect(screen.getByText(/Stop the trading engine before logging in/)).toBeVisible()
  })
})

describe('being logged in to Quotex', () => {
  it('removes the stored login only after asking, and keeps the email and password', async () => {
    let current = quotexStatus({ state: 'logged_in' })
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/quotex/logout',
          () => {
            current = quotexStatus()
            return json(current)
          },
        ],
      ],
    )
    expect(await screen.findByText('Logged in')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Remove the stored login…' }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('email and password stay stored')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.to('POST', '/quotex/logout')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Remove the stored login…' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    expect(await screen.findByRole('button', { name: 'Log in to Quotex' })).toBeVisible()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('cannot be removed while the engine runs', async () => {
    setup(() => quotexStatus({ state: 'logged_in', engine_running: true }))
    expect(await screen.findByRole('button', { name: 'Remove the stored login…' })).toBeDisabled()
  })
})
