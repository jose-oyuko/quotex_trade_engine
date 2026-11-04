import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TelegramLoginStatus } from '../../api/types'
import { makeSnapshot } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import { engineInfo } from './engineFixtures'
import SettingsPage from './SettingsPage'
import { telegramStatus } from './telegramFixtures'

afterEach(() => {
  vi.unstubAllGlobals()
})

const SETTINGS = { items: [], apply_note: 'A saved setting is used from the next start.' }
const SECRETS = { key: 'ok', items: [] }

/** The Settings page against a backend whose Telegram login answers come from `login()`. */
function setup(login: () => TelegramLoginStatus, extra: Parameters<typeof mockApi>[0] = []) {
  const api = mockApi([
    ['GET', '/telegram/login', () => json(login())],
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

const PHONE_HINT = '+254••••••678'

describe('the API id and hash', () => {
  it('are asked for first, with where to get them', async () => {
    let current = telegramStatus({ configured: false })
    const { api, user } = setup(
      () => current,
      [
        ['PUT', '/secrets/telegram_api_id', json({})],
        [
          'PUT',
          '/secrets/telegram_api_hash',
          () => {
            current = telegramStatus()
            return json({})
          },
        ],
      ],
    )
    expect(await screen.findByText(/my\.telegram\.org/)).toBeVisible()
    expect(screen.queryByLabelText('Phone number')).toBeNull() // nothing to log in with yet
    const save = screen.getByRole('button', { name: 'Save the API id and hash' })
    expect(save).toBeDisabled()
    await user.type(screen.getByLabelText('Telegram API id'), ' 123456 ')
    await user.type(screen.getByLabelText('Telegram API hash'), 'abcdef0123')
    expect(screen.getByLabelText('Telegram API hash')).toHaveAttribute('type', 'password')
    await user.click(save)
    expect(await screen.findByLabelText('Phone number')).toBeVisible()
    expect(api.to('PUT', '/secrets/telegram_api_id')[0]?.body).toEqual({ value: '123456' })
    expect(api.to('PUT', '/secrets/telegram_api_hash')[0]?.body).toEqual({ value: 'abcdef0123' })
    expect(document.body.textContent).not.toContain('abcdef0123')
  })

  it('show the server’s reason when the id is refused', async () => {
    const { user } = setup(
      () => telegramStatus({ configured: false }),
      [
        [
          'PUT',
          '/secrets/telegram_api_id',
          apiError(422, 'invalid_secret', 'The Telegram API id is a number (digits only).'),
        ],
      ],
    )
    await user.type(await screen.findByLabelText('Telegram API id'), 'abc')
    await user.type(screen.getByLabelText('Telegram API hash'), 'hash')
    await user.click(screen.getByRole('button', { name: 'Save the API id and hash' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('digits only')
  })

  it('can be changed later, but not while the engine runs', async () => {
    setup(() => telegramStatus({ engine_running: true }))
    expect(await screen.findByRole('button', { name: 'Change them' })).toBeDisabled()
  })
})

describe('logging in', () => {
  it('asks for the phone number in the form Telegram wants', async () => {
    setup(() => telegramStatus())
    expect(await screen.findByLabelText('Phone number')).toBeVisible()
    expect(screen.getByText(/no leading 0/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send me the code' })).toBeDisabled()
  })

  it('goes from the phone number to the code to logged in', async () => {
    let current = telegramStatus()
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/telegram/login/start',
          () => {
            current = telegramStatus({
              state: 'code_sent',
              phone_hint: PHONE_HINT,
              delivery: 'to your Telegram app',
              resends_left: 2,
            })
            return json(current)
          },
        ],
        [
          'POST',
          '/telegram/login/code',
          () => {
            current = telegramStatus({ state: 'logged_in', phone_hint: PHONE_HINT })
            return json(current)
          },
        ],
      ],
    )
    await user.type(await screen.findByLabelText('Phone number'), '+254 712 345 678')
    await user.click(screen.getByRole('button', { name: 'Send me the code' }))
    expect(await screen.findByText(/to your Telegram app/)).toBeVisible()
    expect(screen.getByText(PHONE_HINT)).toBeVisible()
    expect(api.to('POST', '/telegram/login/start')[0]?.body).toEqual({ phone: '+254 712 345 678' })

    await user.type(screen.getByLabelText('Login code'), '12345')
    await user.click(screen.getByRole('button', { name: 'Check the code' }))
    expect(await screen.findByText('Logged in')).toBeVisible()
    expect(api.to('POST', '/telegram/login/code')[0]?.body).toEqual({ code: '12345' })
    expect(screen.queryByLabelText('Login code')).toBeNull()
  })

  it('shows a half-made login after a reload, at the step it had reached', async () => {
    setup(() =>
      telegramStatus({
        state: 'code_sent',
        phone_hint: PHONE_HINT,
        delivery: 'by SMS',
        resends_left: 1,
      }),
    )
    expect(await screen.findByLabelText('Login code')).toBeVisible()
    expect(screen.getByText(/by SMS/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send it another way (1 left)' })).toBeEnabled()
  })

  it('lets a wrong code be typed again without starting over', async () => {
    const { user } = setup(
      () =>
        telegramStatus({
          state: 'code_sent',
          phone_hint: PHONE_HINT,
          delivery: 'by SMS',
          resends_left: 2,
        }),
      [
        [
          'POST',
          '/telegram/login/code',
          apiError(
            422,
            'telegram_code_invalid',
            'That code is not right. Check it and type it again.',
          ),
        ],
      ],
    )
    await user.type(await screen.findByLabelText('Login code'), '00000')
    await user.click(screen.getByRole('button', { name: 'Check the code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right')
    expect(screen.getByLabelText('Login code')).toHaveValue('00000') // still there to correct
  })

  it('asks for the code to be sent another way, and says how many ways are left', async () => {
    let current = telegramStatus({
      state: 'code_sent',
      phone_hint: PHONE_HINT,
      delivery: 'to your Telegram app',
      resends_left: 2,
    })
    const { user } = setup(
      () => current,
      [
        [
          'POST',
          '/telegram/login/resend',
          () => {
            current = telegramStatus({ ...current, delivery: 'by SMS', resends_left: 1 })
            return json(current)
          },
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Send it another way (2 left)' }))
    expect(await screen.findByText(/by SMS/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send it another way (1 left)' })).toBeVisible()
  })

  it('cannot ask again when no way is left', async () => {
    setup(() =>
      telegramStatus({
        state: 'code_sent',
        phone_hint: PHONE_HINT,
        delivery: 'by SMS',
        resends_left: 0,
      }),
    )
    expect(
      await screen.findByRole('button', { name: 'Send it another way (0 left)' }),
    ).toBeDisabled()
  })

  it('goes back to the phone number with "Use another number"', async () => {
    let current = telegramStatus({ state: 'code_sent', phone_hint: PHONE_HINT, delivery: 'by SMS' })
    const { user } = setup(
      () => current,
      [
        [
          'POST',
          '/telegram/login/cancel',
          () => {
            current = telegramStatus()
            return json(current)
          },
        ],
      ],
    )
    await user.click(await screen.findByRole('button', { name: 'Use another number' }))
    expect(await screen.findByLabelText('Phone number')).toBeVisible()
  })

  it('asks for the two-step password when the account has one', async () => {
    let current = telegramStatus({ state: 'password_needed', phone_hint: PHONE_HINT })
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/telegram/login/password',
          () => {
            current = telegramStatus({ state: 'logged_in', phone_hint: PHONE_HINT })
            return json(current)
          },
        ],
      ],
    )
    const box = await screen.findByLabelText('Two-step verification password')
    expect(box).toHaveAttribute('type', 'password')
    await user.type(box, 'my two step secret')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText('Logged in')).toBeVisible()
    expect(api.to('POST', '/telegram/login/password')[0]?.body).toEqual({
      password: 'my two step secret',
    })
    expect(document.body.textContent).not.toContain('my two step secret')
  })

  it('says how long to wait when Telegram asks for patience', async () => {
    const { user } = setup(
      () => telegramStatus(),
      [
        [
          'POST',
          '/telegram/login/start',
          apiError(
            429,
            'telegram_wait',
            'Telegram asks you to wait before trying again: about 5 minute(s) (300 seconds).',
          ),
        ],
      ],
    )
    await user.type(await screen.findByLabelText('Phone number'), '+254712345678')
    await user.click(screen.getByRole('button', { name: 'Send me the code' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('about 5 minute(s)')
  })

  it('does not offer a new login while the engine is running', async () => {
    const { user } = setup(() => telegramStatus({ engine_running: true }))
    await user.type(await screen.findByLabelText('Phone number'), '+254712345678')
    expect(screen.getByRole('button', { name: 'Send me the code' })).toBeDisabled()
  })
})

describe('being logged in', () => {
  it('shows who, and logs out only after asking', async () => {
    let current = telegramStatus({ state: 'logged_in', phone_hint: PHONE_HINT })
    const { api, user } = setup(
      () => current,
      [
        [
          'POST',
          '/telegram/logout',
          () => {
            current = telegramStatus()
            return json(current)
          },
        ],
      ],
    )
    expect(await screen.findByText('Logged in')).toBeVisible()
    expect(screen.getByText(PHONE_HINT, { exact: false })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Log out of Telegram…' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.to('POST', '/telegram/logout')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Log out of Telegram…' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Log out' }))
    expect(await screen.findByLabelText('Phone number')).toBeVisible()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('cannot log out while the engine runs, and says why', async () => {
    setup(() =>
      telegramStatus({ state: 'logged_in', phone_hint: PHONE_HINT, engine_running: true }),
    )
    expect(await screen.findByRole('button', { name: 'Log out of Telegram…' })).toBeDisabled()
    expect(screen.getByText(/Stop the trading engine before/)).toBeVisible()
  })

  it('warns when the stored login cannot be read', async () => {
    setup(() =>
      telegramStatus({ problem: 'The stored Telegram login cannot be read. Log in again.' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot be read')
    expect(screen.getByLabelText('Phone number')).toBeVisible() // and the way out is right there
  })
})
