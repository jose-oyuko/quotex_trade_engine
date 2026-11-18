import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeSession, page } from '../../test/fixtures'
import { apiError, json, mockApi } from '../../test/utils'
import SessionFormPage from './SessionFormPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

function setup(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/sessions/new" element={<SessionFormPage />} />
          <Route path="/sessions/:id/edit" element={<SessionFormPage />} />
          <Route path="/sessions" element={<p>the sessions list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const listed = ['GET', '/sessions', json(page([makeSession()]))] as const

describe('adding a session', () => {
  it('sends the new session to the server and goes back to the list', async () => {
    const api = mockApi([['POST', '/sessions', json(makeSession(), 201)], listed])
    const user = setup('/sessions/new')
    await user.type(screen.getByLabelText('Name'), 'London open')
    await user.click(screen.getByRole('button', { name: 'Create session' }))

    expect(await screen.findByText('the sessions list')).toBeInTheDocument()
    expect(api.to('POST', '/sessions')[0]?.body).toEqual({
      name: 'London open',
      enabled: true,
      broker: 'quotex',
      asset: 'EURUSD',
      duration_s: 300,
      start_time: '11:00',
      end_time: '12:00',
      timezone: 'UTC',
      repeat: 'weekdays',
      weekdays: [0, 1, 2, 3, 4],
      mode: 'sequential',
      max_open_pairs: 1,
      pause_s: 0,
      profit_target: null,
      loss_limit: null,
      max_pairs: null,
      strategy: {
        strategy: 'flip_every_loss',
        base_stake: '1.00',
        max_steps: 3,
        multipliers: ['2.0', '2.5', '3.0'],
        min_payout_pct: 80,
      },
    })
  })

  it('does not send a session without a name', async () => {
    const api = mockApi([['POST', '/sessions', json(makeSession(), 201)]])
    const user = setup('/sessions/new')
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByText('Give the session a name')).toBeInTheDocument()
    expect(api.to('POST', '/sessions')).toHaveLength(0)
  })

  it('shows what the server refuses at the top, in words (a window that overlaps)', async () => {
    mockApi([
      [
        'POST',
        '/sessions',
        apiError(409, 'session_overlap', 'The window overlaps the one of the session "Night".'),
      ],
    ])
    const user = setup('/sessions/new')
    await user.type(screen.getByLabelText('Name'), 'Clash')
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('overlaps the one of the session')
    expect(screen.queryByText('the sessions list')).not.toBeInTheDocument()
  })

  it('shows what the server says about one field next to that field', async () => {
    mockApi([
      [
        'POST',
        '/sessions',
        apiError(422, 'validation_error', 'The request is not valid.', [
          { field: 'strategy.multipliers.1', message: 'must be greater than 0' },
        ]),
      ],
    ])
    const user = setup('/sessions/new')
    await user.type(screen.getByLabelText('Name'), 'Bad')
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByText('must be greater than 0')).toBeInTheDocument()
  })
})

describe('the choices that change the form', () => {
  it('asks for the days only when they are chosen, and wants at least one', async () => {
    const api = mockApi([['POST', '/sessions', json(makeSession(), 201)], listed])
    const user = setup('/sessions/new')
    expect(screen.queryByRole('group', { name: 'Days of the week' })).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('How often'), 'chosen')
    const days = screen.getByRole('group', { name: 'Days of the week' })
    const boxes = Array.from(days.querySelectorAll('input'))
    expect(boxes.map((box) => box.checked)).toEqual([true, true, true, true, true, false, false])

    await user.type(screen.getByLabelText('Name'), 'Days')
    for (const box of boxes.slice(0, 5)) await user.click(box) // clear Monday to Friday
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByText('Choose at least one day')).toBeInTheDocument()
    expect(api.to('POST', '/sessions')).toHaveLength(0)

    await user.click(boxes[1] as HTMLElement) // Tue
    await user.click(boxes[3] as HTMLElement) // Thu
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    await waitFor(() => {
      expect(api.to('POST', '/sessions')).toHaveLength(1)
    })
    expect(api.to('POST', '/sessions')[0]?.body).toMatchObject({
      repeat: 'weekdays',
      weekdays: [1, 3],
    })
  })

  it('offers the open-pair limit for a pair at every candle, and the pause for one at a time', async () => {
    const api = mockApi([['POST', '/sessions', json(makeSession(), 201)], listed])
    const user = setup('/sessions/new')
    expect(screen.getByLabelText('Pause after a pair (seconds)')).toBeInTheDocument()
    expect(screen.queryByLabelText('Open pairs at most')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Pairs'), 'every_candle')
    expect(screen.queryByLabelText('Pause after a pair (seconds)')).not.toBeInTheDocument()
    const limit = screen.getByLabelText('Open pairs at most')
    await user.clear(limit)
    await user.type(limit, '3')
    await user.type(screen.getByLabelText('Name'), 'Candles')
    await user.click(screen.getByRole('button', { name: 'Create session' }))

    await waitFor(() => {
      expect(api.to('POST', '/sessions')).toHaveLength(1)
    })
    expect(api.to('POST', '/sessions')[0]?.body).toMatchObject({
      mode: 'every_candle',
      max_open_pairs: 3,
      pause_s: 0,
    })
  })

  it('has no multipliers for a strategy without follow-ups', async () => {
    setup('/sessions/new')
    expect(screen.getByLabelText('Multiplier for step 3')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Strategy'), 'no_martingale')
    expect(screen.queryByLabelText('Multiplier for step 1')).not.toBeInTheDocument()
  })
})

describe('the plain-words checks', () => {
  it('says in figures the most that can be at stake', async () => {
    const user = setup('/sessions/new')
    // base 1.00 and multipliers 2.0, 2.5 and 3.0: two first trades plus the steps = 9.5
    const note = screen.getByRole('note', { name: 'The most that can be at stake' })
    expect(note).toHaveTextContent('up to 9.5')
    expect(note).toHaveTextContent('stakes only')

    await user.selectOptions(screen.getByLabelText('Pairs'), 'every_candle')
    await user.clear(screen.getByLabelText('Open pairs at most'))
    await user.type(screen.getByLabelText('Open pairs at most'), '4')
    expect(screen.getByRole('note', { name: 'The most that can be at stake' })).toHaveTextContent(
      'With 4 pairs open at once, up to 38',
    )
  })

  it('warns when the start is not on a candle boundary', () => {
    setup('/sessions/new')
    expect(screen.queryByText(/is not on a 5-minute candle boundary/)).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Starts at'), { target: { value: '11:02' } })
    expect(screen.getByText(/11:02 is not on a 5-minute candle boundary/)).toBeInTheDocument()
  })

  it('says that the loss limit is not a cap', () => {
    setup('/sessions/new')
    expect(
      screen.getByText((_, element) =>
        /not a cap on the loss/.test(element?.tagName === 'P' ? element.textContent : ''),
      ),
    ).toBeInTheDocument()
  })
})

describe('editing a session', () => {
  it('shows what was saved and sends the changes', async () => {
    const api = mockApi([
      [
        'GET',
        '/sessions/1',
        json(makeSession({ profit_target: '10.00', mode: 'every_candle', max_open_pairs: 2 })),
      ],
      ['PUT', '/sessions/1', json(makeSession())],
      listed,
    ])
    const user = setup('/sessions/1/edit')
    expect(await screen.findByDisplayValue('London open')).toBeInTheDocument()
    expect(screen.getByLabelText('Profit target')).toHaveValue('10.00')
    expect(screen.getByLabelText('Open pairs at most')).toHaveValue(2)

    await user.clear(screen.getByLabelText('Name'))
    await user.type(screen.getByLabelText('Name'), 'Renamed')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('the sessions list')).toBeInTheDocument()
    expect(api.to('PUT', '/sessions/1')[0]?.body).toMatchObject({
      name: 'Renamed',
      mode: 'every_candle',
      max_open_pairs: 2,
      profit_target: '10.00',
    })
  })

  it('says so when the session cannot be edited because it is running', async () => {
    mockApi([
      ['GET', '/sessions/1', json(makeSession())],
      [
        'PUT',
        '/sessions/1',
        apiError(409, 'session_in_use', 'the session is running: stop it first'),
      ],
    ])
    const user = setup('/sessions/1/edit')
    await screen.findByDisplayValue('London open')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('the session is running')
  })

  it('refuses an id that is not a number', () => {
    setup('/sessions/abc/edit')
    expect(screen.getByRole('alert')).toHaveTextContent('That is not a session.')
  })
})

describe('a session on Deriv (decision D-75)', () => {
  const DERIV_ASSETS = {
    available: true,
    reason: null,
    items: [
      {
        asset: 'R_75',
        name: 'Volatility 75 Index',
        market: 'synthetic_index',
        is_open: true,
        lengths: [{ min_s: 15, max_s: 31_536_000 }],
      },
      {
        asset: 'EURUSD',
        name: 'EUR/USD',
        market: 'forex',
        is_open: true,
        lengths: [{ min_s: 900, max_s: 31_536_000 }],
      },
      { asset: 'GBPUSD', name: 'GBP/USD', market: 'forex', is_open: false, lengths: null },
    ],
  }

  it('picks the asset from Deriv’s list, grouped by market, and sends the broker', async () => {
    const api = mockApi([
      ['GET', '/deriv/assets', json(DERIV_ASSETS)],
      ['POST', '/sessions', json(makeSession({ broker: 'deriv' }), 201)],
      listed,
    ])
    const user = setup('/sessions/new')
    await user.type(screen.getByLabelText('Name'), 'Vol 75')
    await user.selectOptions(screen.getByLabelText('Broker'), 'deriv')
    const asset = await screen.findByRole('combobox', { name: 'Asset' })
    const groups = within(asset).getAllByRole('group')
    expect(groups.map((g) => g.getAttribute('label'))).toEqual(['Forex pairs', 'Synthetic indices'])
    expect(
      within(asset).getByRole('option', { name: 'GBP/USD (GBPUSD), closed now' }),
    ).toBeVisible()

    await user.selectOptions(asset, 'R_75')
    await user.selectOptions(screen.getByLabelText('Trade length'), '60')
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByText('the sessions list')).toBeInTheDocument()
    expect(api.to('POST', '/sessions')[0]?.body).toMatchObject({
      broker: 'deriv',
      asset: 'R_75',
      duration_s: 60,
    })
  })

  it('offers only the trade lengths the asset allows, and says why', async () => {
    mockApi([['GET', '/deriv/assets', json(DERIV_ASSETS)]])
    const user = setup('/sessions/new')
    await user.selectOptions(screen.getByLabelText('Broker'), 'deriv')
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Asset' }), 'EURUSD')
    const length = screen.getByLabelText('Trade length')
    expect(
      within(length).getByRole('option', { name: '1 minute (M1) (not offered)' }),
    ).toBeDisabled()
    expect(within(length).getByRole('option', { name: '15 minutes (M15)' })).toBeEnabled()
    // the default 5 minutes is not offered on EURUSD: said plainly
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Deriv does not offer 5 min Rise/Fall on EURUSD: it offers 15 min to 365 days',
    )
    await user.selectOptions(length, '900')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('without Deriv’s list, the asset is typed and the reason is given', async () => {
    mockApi([
      [
        'GET',
        '/deriv/assets',
        json({ available: false, reason: 'The trading engine is not running.', items: [] }),
      ],
    ])
    const user = setup('/sessions/new')
    await user.selectOptions(screen.getByLabelText('Broker'), 'deriv')
    expect(await screen.findByText(/now: The trading engine is not running\./)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Asset' })).toHaveValue('EURUSD')
  })

  it('refuses an OTC pair on Deriv before sending anything', async () => {
    const api = mockApi([
      [
        'GET',
        '/deriv/assets',
        json({ available: false, reason: 'Deriv is not connected.', items: [] }),
      ],
      ['POST', '/sessions', json(makeSession(), 201)],
    ])
    const user = setup('/sessions/new')
    await user.type(screen.getByLabelText('Name'), 'Weekend')
    await user.selectOptions(screen.getByLabelText('Broker'), 'deriv')
    const asset = await screen.findByRole('textbox', { name: 'Asset' })
    await user.clear(asset)
    await user.type(asset, 'EURUSD_otc')
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(
      await screen.findByText('Deriv has no OTC pairs: use EURUSD, or a synthetic index like R_75'),
    ).toBeInTheDocument()
    expect(api.to('POST', '/sessions')).toHaveLength(0)
  })

  it('shows the refusal of the server in words (a length Deriv does not offer)', async () => {
    mockApi([
      [
        'GET',
        '/deriv/assets',
        json({ available: false, reason: 'Deriv is not connected.', items: [] }),
      ],
      [
        'POST',
        '/sessions',
        apiError(
          422,
          'invalid_session',
          'Deriv does not offer 1 min Rise/Fall on EURUSD: it offers 15 min to 365 days',
        ),
      ],
    ])
    const user = setup('/sessions/new')
    await user.type(screen.getByLabelText('Name'), 'Too short')
    await user.selectOptions(screen.getByLabelText('Broker'), 'deriv')
    await user.click(screen.getByRole('button', { name: 'Create session' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Deriv does not offer 1 min Rise/Fall on EURUSD',
    )
  })

  it('keeps a session on Deriv when it is edited, with its asset shown even if Deriv’s list lacks it', async () => {
    mockApi([
      [
        'GET',
        '/sessions/1',
        json(makeSession({ broker: 'deriv', asset: '1HZ100V', duration_s: 60 })),
      ],
      ['GET', '/deriv/assets', json(DERIV_ASSETS)],
    ])
    setup('/sessions/1/edit')
    const asset = await screen.findByRole('combobox', { name: 'Asset' })
    expect(asset).toHaveValue('1HZ100V')
    expect(within(asset).getByRole('option', { name: '1HZ100V (not listed)' })).toBeVisible()
    expect(screen.getByLabelText('Broker')).toHaveValue('deriv')
  })
})
