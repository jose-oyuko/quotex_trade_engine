import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SecretItem, SecretsOut } from '../../api/types'
import { apiError, json, mockApi } from '../../test/utils'
import { DerivPanel } from './DerivPanel'

afterEach(() => {
  vi.unstubAllGlobals()
})

function secret(name: string, label: string, isSet: boolean): SecretItem {
  return {
    name,
    label,
    help: `help for ${label}`,
    group: 'deriv',
    is_set: isSet,
    readable: isSet,
    updated_at: isSet ? '2026-11-17T10:00:00Z' : null,
  }
}

function secrets({ appId = true, demo = true, real = false } = {}): SecretsOut {
  return {
    key: 'ok',
    items: [
      { ...secret('quotex_email', 'Quotex email', true), group: 'logins' },
      secret('deriv_app_id', 'Deriv app id', appId),
      secret('deriv_token_demo', 'Deriv demo token', demo),
      secret('deriv_token_real', 'Deriv real token', real),
    ],
  }
}

function setup(data: SecretsOut, routes: Parameters<typeof mockApi>[0] = []) {
  const api = mockApi(routes)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <DerivPanel data={data} />
    </QueryClientProvider>,
  )
  return { api, user: userEvent.setup() }
}

describe('the Deriv card', () => {
  it('lists Deriv’s three logins only, and says to give tokens Read and Trade only', () => {
    setup(secrets({ real: false }))
    const card = screen.getByRole('group', { name: 'Deriv' })
    expect(within(card).getByText('Deriv app id')).toBeVisible()
    expect(within(card).getByText('Deriv demo token')).toBeVisible()
    expect(within(card).getByText('Deriv real token')).toBeVisible()
    expect(within(card).queryByText('Quotex email')).toBeNull()
    expect(within(card).getByText(/only the Read and Trade permissions/)).toBeVisible()
    expect(within(card).getByRole('link', { name: /developer site/ })).toHaveAttribute(
      'href',
      'https://developers.deriv.com',
    )
  })

  it('stores a token like any other secret, without showing it again', async () => {
    const { api, user } = setup(secrets({ demo: false }), [
      ['PUT', '/secrets/deriv_token_demo', json(secret('deriv_token_demo', 'x', true))],
      ['GET', '/secrets', json(secrets())],
    ])
    await user.click(screen.getByRole('button', { name: 'Set Deriv demo token' }))
    await user.type(screen.getByLabelText('New value for Deriv demo token'), 'tok-123')
    await user.click(screen.getByRole('button', { name: 'Save Deriv demo token' }))
    expect(api.to('PUT', '/secrets/deriv_token_demo')[0]?.body).toEqual({ value: 'tok-123' })
    expect(await screen.findByRole('button', { name: 'Set Deriv demo token' })).toBeVisible()
    expect(screen.queryByDisplayValue('tok-123')).toBeNull()
  })

  it('checks the demo token and says which account it opens, without trading', async () => {
    const { api, user } = setup(secrets(), [
      [
        'POST',
        '/deriv/check',
        json({ account_id: 'VRTC100', account_type: 'demo', currency: 'USD', balance: '10000.00' }),
      ],
    ])
    await user.click(screen.getByRole('button', { name: 'Check the demo token' }))
    const result = await screen.findByRole('status')
    expect(result).toHaveTextContent('This token opens account VRTC100, a demo account, in USD')
    expect(result).toHaveTextContent('10,000.00')
    expect(result).toHaveTextContent('Nothing was traded.')
    expect(api.to('POST', '/deriv/check')[0]?.body).toEqual({ account_type: 'demo' })
  })

  it('says in words when Deriv refuses the token', async () => {
    const { user } = setup(secrets(), [
      [
        'POST',
        '/deriv/check',
        apiError(422, 'deriv_login_refused', 'Deriv refused the token (401: Invalid token).'),
      ],
    ])
    await user.click(screen.getByRole('button', { name: 'Check the demo token' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Deriv refused the token (401: Invalid token).',
    )
  })

  it('can check only what is stored: the demo token needs the app id, the real one appears when stored', () => {
    setup(secrets({ appId: false }))
    expect(screen.getByRole('button', { name: 'Check the demo token' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Check the real token' })).toBeNull()
  })

  it('checks the real token with the real account', async () => {
    const { api, user } = setup(secrets({ real: true }), [
      [
        'POST',
        '/deriv/check',
        json({ account_id: 'CR200', account_type: 'real', currency: 'USD', balance: null }),
      ],
    ])
    await user.click(screen.getByRole('button', { name: 'Check the real token' }))
    expect(await screen.findByRole('status')).toHaveTextContent('a REAL MONEY account')
    expect(api.to('POST', '/deriv/check')[0]?.body).toEqual({ account_type: 'real' })
  })
})
