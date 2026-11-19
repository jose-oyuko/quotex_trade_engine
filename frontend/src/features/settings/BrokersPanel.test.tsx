import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BrokersOut } from '../../api/types'
import { apiError, json, mockApi } from '../../test/utils'
import { BrokersPanel } from './BrokersPanel'

afterEach(() => {
  vi.unstubAllGlobals()
})

function brokers(quotex: Partial<BrokersOut['items'][number]> = {}): BrokersOut {
  return {
    items: [
      { broker: 'quotex', enabled: true, state: 'connected', detail: null, ...quotex },
      { broker: 'deriv', enabled: true, state: 'connected', detail: null },
    ],
  }
}

function setup(data: BrokersOut, routes: Parameters<typeof mockApi>[0] = []) {
  const api = mockApi(routes)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <BrokersPanel data={data} />
    </QueryClientProvider>,
  )
  return { api, user: userEvent.setup() }
}

describe('the Brokers card', () => {
  it('shows each broker with its state in words', () => {
    setup(brokers())
    const card = screen.getByRole('group', { name: 'Brokers' })
    expect(within(card).getAllByText('connected')).toHaveLength(2)
    expect(within(card).getByRole('button', { name: 'Switch Quotex off' })).toBeEnabled()
    expect(within(card).getByRole('button', { name: 'Switch Deriv off' })).toBeEnabled()
  })

  it('switches a broker off', async () => {
    const { api, user } = setup(brokers(), [
      ['PUT', '/brokers/quotex', json(brokers({ enabled: false, state: 'off' }))],
    ])
    await user.click(screen.getByRole('button', { name: 'Switch Quotex off' }))
    expect(api.to('PUT', '/brokers/quotex')[0]?.body).toEqual({ enabled: false })
  })

  it('switches an off broker back on', async () => {
    const { api, user } = setup(brokers({ enabled: false, state: 'off' }), [
      ['PUT', '/brokers/quotex', json(brokers())],
    ])
    expect(screen.getByText('switched off')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Switch Quotex on' }))
    expect(api.to('PUT', '/brokers/quotex')[0]?.body).toEqual({ enabled: true })
  })

  it('says in words why a broker cannot be switched off', async () => {
    const { user } = setup(brokers(), [
      [
        'PUT',
        '/brokers/quotex',
        apiError(
          409,
          'broker_switch_refused',
          'Quotex cannot be switched off while 1 trade(s) are open on it: wait for them to finish, or stop them first.',
        ),
      ],
    ])
    await user.click(screen.getByRole('button', { name: 'Switch Quotex off' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Quotex cannot be switched off while 1 trade(s) are open on it',
    )
  })

  it('shows why a broker needs the owner', () => {
    setup(brokers({ state: 'needs_you', detail: 'Quotex asked for an email PIN.' }))
    expect(screen.getByText('needs you')).toBeVisible()
    expect(screen.getByRole('note')).toHaveTextContent('Quotex asked for an email PIN.')
  })
})
