import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SecretItem, SecretsOut, SettingsOut } from '../../api/types'
import { makeSnapshot } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import { engineInfo } from './engineFixtures'
import { telegramStatus } from './telegramFixtures'
import SettingsPage from './SettingsPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const BASE = [
  ['GET', '/engine', json(engineInfo())],
  ['GET', '/status', json(makeSnapshot())],
  ['GET', '/telegram/login', json(telegramStatus())],
] as const

const NOTE = 'A saved setting is used from the next start of the application.'

function settings(overrides: Partial<Record<string, Partial<SettingsOut['items'][number]>>> = {}) {
  const base: SettingsOut = {
    apply_note: NOTE,
    items: [
      {
        key: 'log_level',
        label: 'Log detail',
        help: 'How much the application writes to its log.',
        kind: 'choice',
        choices: ['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        value: 'INFO',
        default_value: 'INFO',
        source: 'default',
      },
      {
        key: 'quotex_host',
        label: 'Quotex address',
        help: 'The domain Quotex is reached at.',
        kind: 'text',
        choices: [],
        value: 'quotex.com',
        default_value: 'quotex.com',
        source: 'environment',
      },
    ],
  }
  return {
    ...base,
    items: base.items.map((item) => ({ ...item, ...(overrides[item.key] ?? {}) })),
  }
}

function secret(name: string, label: string, over: Partial<SecretItem> = {}): SecretItem {
  return {
    name,
    label,
    help: `help for ${label}`,
    group: 'logins',
    is_set: false,
    readable: false,
    updated_at: null,
    ...over,
  }
}

function secrets(over: Partial<SecretsOut> = {}, items?: SecretItem[]): SecretsOut {
  return {
    key: 'ok',
    items: items ?? [
      secret('quotex_email', 'Quotex email'),
      secret('quotex_password', 'Quotex password'),
      secret('telegram_api_id', 'Telegram API id', { group: 'telegram' }),
      secret('telegram_api_hash', 'Telegram API hash', { group: 'telegram' }),
    ],
    ...over,
  }
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('application settings', () => {
  it('shows each setting with where its value comes from', async () => {
    mockApi([...BASE, ['GET', '/settings', json(settings())], ['GET', '/secrets', json(secrets())]])
    setup()
    expect(await screen.findByLabelText('Log detail')).toHaveValue('INFO')
    expect(screen.getByLabelText('Quotex address')).toHaveValue('quotex.com')
    expect(screen.getByText('built-in default')).toBeVisible()
    expect(screen.getByText('from backend/.env')).toBeVisible()
  })

  it('saves only what was changed and says when it applies', async () => {
    let saved = false
    const api = mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      ['GET', '/secrets', json(secrets())],
      [
        'PUT',
        '/settings',
        () => {
          saved = true
          return json(settings({ log_level: { value: 'DEBUG', source: 'database' } }))
        },
      ],
    ])
    const user = setup()
    const save = await screen.findByRole('button', { name: 'Save' })
    expect(save).toBeDisabled() // nothing changed yet
    await user.selectOptions(screen.getByLabelText('Log detail'), 'DEBUG')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Saved. ' + NOTE)
    expect(saved).toBe(true)
    expect(api.to('PUT', '/settings')[0]?.body).toEqual({ values: { log_level: 'DEBUG' } })
    expect(screen.getByText('set here')).toBeVisible()
  })

  it('shows the server’s reason when a value is refused', async () => {
    mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      ['GET', '/secrets', json(secrets())],
      [
        'PUT',
        '/settings',
        apiError(422, 'invalid_setting', 'The Quotex address must be a bare domain name.'),
      ],
    ])
    const user = setup()
    const host = await screen.findByLabelText('Quotex address')
    await user.clear(host)
    await user.type(host, 'not a host!')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('bare domain name')
  })

  it('goes back to the default by removing the stored value', async () => {
    const api = mockApi([
      ...BASE,
      [
        'GET',
        '/settings',
        json(settings({ quotex_host: { value: 'mine.example', source: 'database' } })),
      ],
      ['GET', '/secrets', json(secrets())],
      ['PUT', '/settings', json(settings())],
    ])
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Go back to quotex.com' }))
    expect(api.to('PUT', '/settings')[0]?.body).toEqual({ values: { quotex_host: null } })
    expect(await screen.findByText('from backend/.env')).toBeVisible()
  })
})

describe('stored logins', () => {
  it('lists what is stored without ever showing a value', async () => {
    mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      [
        'GET',
        '/secrets',
        json(
          secrets({}, [
            secret('quotex_email', 'Quotex email', { is_set: true, readable: true }),
            secret('quotex_password', 'Quotex password', { is_set: true, readable: false }),
            secret('telegram_api_hash', 'Telegram API hash', {
              group: 'telegram',
              is_set: true,
              readable: true,
            }),
          ]),
        ),
      ],
    ])
    setup()
    expect(await screen.findByText('Stored')).toBeVisible()
    expect(screen.getByText('Stored, cannot be read')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Replace Quotex email' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Replace Quotex password' })).toBeVisible()
    expect(document.querySelectorAll('input[type=password]')).toHaveLength(0)
  })

  it('leaves the Telegram entries to the Telegram box', async () => {
    mockApi([...BASE, ['GET', '/settings', json(settings())], ['GET', '/secrets', json(secrets())]])
    setup()
    expect(await screen.findByRole('button', { name: 'Set Quotex email' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Telegram API/ })).toBeNull()
  })

  it('stores a value, hides the box again and keeps no copy on the page', async () => {
    let stored = false
    const api = mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      [
        'GET',
        '/secrets',
        () =>
          json(
            secrets({}, [
              secret('quotex_email', 'Quotex email'),
              secret('quotex_password', 'Quotex password', {
                is_set: stored,
                readable: stored,
              }),
              secret('telegram_api_hash', 'Telegram API hash'),
            ]),
          ),
      ],
      [
        'PUT',
        '/secrets/quotex_password',
        () => {
          stored = true
          return json(
            secret('quotex_password', 'Quotex password', { is_set: true, readable: true }),
          )
        },
      ],
    ])
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Set Quotex password' }))
    const box = screen.getByLabelText('New value for Quotex password')
    expect(box).toHaveAttribute('type', 'password')
    await user.type(box, 'my private password')
    await user.click(screen.getByRole('button', { name: 'Save Quotex password' }))
    expect(await screen.findByText('Stored')).toBeVisible()
    expect(api.to('PUT', '/secrets/quotex_password')[0]?.body).toEqual({
      value: 'my private password',
    })
    expect(screen.queryByLabelText('New value for Quotex password')).toBeNull()
    expect(document.body.textContent).not.toContain('my private password')
    expect(screen.getByRole('button', { name: 'Replace Quotex password' })).toBeVisible()
  })

  it('can be cancelled without sending anything', async () => {
    const api = mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      ['GET', '/secrets', json(secrets())],
    ])
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Set Quotex email' }))
    await user.type(screen.getByLabelText('New value for Quotex email'), 'half typed')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByLabelText('New value for Quotex email')).toBeNull()
    expect(api.to('PUT', '/secrets/quotex_email')).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: 'Set Quotex email' }))
    expect(screen.getByLabelText('New value for Quotex email')).toHaveValue('') // not remembered
  })

  it('asks before removing, and removes only when confirmed', async () => {
    const api = mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      [
        'GET',
        '/secrets',
        json(
          secrets({}, [secret('quotex_email', 'Quotex email', { is_set: true, readable: true })]),
        ),
      ],
      ['DELETE', '/secrets/quotex_email', new Response(null, { status: 204 })],
    ])
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Remove Quotex email' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(api.to('DELETE', '/secrets/quotex_email')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Remove Quotex email' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))
    await vi.waitFor(() => {
      expect(api.to('DELETE', '/secrets/quotex_email')).toHaveLength(1)
    })
  })

  it('explains a missing key, and does not let anything be stored without it', async () => {
    mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      ['GET', '/secrets', json(secrets({ key: 'missing' }))],
    ])
    setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('npm run key:create')
    expect(screen.getByRole('button', { name: 'Set Quotex email' })).toBeDisabled()
  })

  it('explains an invalid key', async () => {
    mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      ['GET', '/secrets', json(secrets({ key: 'invalid' }))],
    ])
    setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('not a valid key')
  })

  it('lets a value that cannot be read be typed again', async () => {
    mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      [
        'GET',
        '/secrets',
        json(
          secrets({}, [
            secret('quotex_password', 'Quotex password', { is_set: true, readable: false }),
          ]),
        ),
      ],
    ])
    setup()
    expect(await screen.findByText('Stored, cannot be read')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Replace Quotex password' })).toBeEnabled()
  })

  it('shows the server’s reason when storing fails', async () => {
    mockApi([
      ...BASE,
      ['GET', '/settings', json(settings())],
      ['GET', '/secrets', json(secrets())],
      [
        'PUT',
        '/secrets/quotex_email',
        apiError(422, 'invalid_secret', 'Quotex email must not be empty.'),
      ],
    ])
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Set Quotex email' }))
    await user.type(screen.getByLabelText('New value for Quotex email'), ' ')
    await user.click(screen.getByRole('button', { name: 'Save Quotex email' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('must not be empty')
  })
})
