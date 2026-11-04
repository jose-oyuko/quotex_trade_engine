import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, json, mockApi } from '../../test/utils'
import { EnvLoginsNotice } from './EnvLoginsNotice'

afterEach(() => {
  vi.unstubAllGlobals()
})

const item = (label: string, in_env: boolean, stored: boolean) => ({ label, in_env, stored })

function setup(routes: Parameters<typeof mockApi>[0]) {
  const api = mockApi(routes)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <EnvLoginsNotice />
    </QueryClientProvider>,
  )
  return { api, user: userEvent.setup() }
}

describe('old logins in backend/.env', () => {
  it('says nothing when .env holds none', async () => {
    const { api } = setup([
      ['GET', '/settings/env-logins', json({ items: [item('Quotex email', false, false)] })],
    ])
    await vi.waitFor(() => {
      expect(api.to('GET', '/settings/env-logins')).toHaveLength(1)
    })
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('names the logins still in plain text and moves them with one button', async () => {
    let moved = false
    const { api, user } = setup([
      [
        'GET',
        '/settings/env-logins',
        () =>
          json({
            items: [item('Quotex email', true, moved), item('Quotex password', true, moved)],
          }),
      ],
      [
        'POST',
        '/settings/env-logins/import',
        () => {
          moved = true
          return json({
            imported: ['Quotex email', 'Quotex password'],
            items: [item('Quotex email', true, true), item('Quotex password', true, true)],
          })
        },
      ],
      ['GET', '/secrets', json({ key: 'ok', items: [] })],
      ['GET', '/engine', json({})],
      ['GET', '/telegram/login', json({})],
    ])
    expect(await screen.findByText(/Quotex email, Quotex password/)).toBeVisible()
    expect(screen.getByText(/plain text/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Move them into the encrypted store' }))
    expect(await screen.findByText(/Moved\./)).toBeVisible()
    expect(screen.getByText(/no longer used/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /Move them/ })).toBeNull()
    expect(api.to('POST', '/settings/env-logins/import')).toHaveLength(1)
  })

  it('reminds the owner to delete the lines once everything is stored', async () => {
    setup([['GET', '/settings/env-logins', json({ items: [item('Quotex email', true, true)] })]])
    expect(await screen.findByText(/You can delete those lines/)).toBeVisible()
    expect(screen.getByText('npm run env:import')).toBeVisible()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('shows the server’s reason when moving fails (no SECRET_KEY)', async () => {
    const { user } = setup([
      ['GET', '/settings/env-logins', json({ items: [item('Quotex email', true, false)] })],
      [
        'POST',
        '/settings/env-logins/import',
        apiError(503, 'secret_key_missing', 'SECRET_KEY is not set in backend/.env.'),
      ],
    ])
    await user.click(
      await screen.findByRole('button', { name: 'Move them into the encrypted store' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('SECRET_KEY is not set')
  })

  it('stays out of the way when the list cannot be had', async () => {
    const { api } = setup([['GET', '/settings/env-logins', new Error('offline')]])
    await vi.waitFor(() => {
      expect(api.to('GET', '/settings/env-logins')).toHaveLength(1)
    })
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
