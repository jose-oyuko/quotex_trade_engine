import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeGroup, makeSignal, page } from '../../test/fixtures'
import { json, mockApi, renderWith } from '../../test/utils'
import SignalsPage from './SignalsPage'

afterEach(() => {
  vi.unstubAllGlobals()
})

const GROUPS = ['GET', '/groups', json(page([makeGroup()]))] as const

describe('SignalsPage', () => {
  it('shows every message with what became of it and why', async () => {
    mockApi([
      GROUPS,
      [
        'GET',
        '/signals',
        json(
          page([
            makeSignal(),
            makeSignal({
              id: 's2',
              status: 'not_parsed',
              reason: 'no direction in the message',
              raw_text: 'good morning everyone',
              asset: null,
              direction: null,
              duration_s: null,
            }),
            makeSignal({
              id: 's3',
              status: 'ignored',
              reason: 'chain active: flip_every_loss ignores new signals',
            }),
          ]),
        ),
      ],
    ])
    renderWith(<SignalsPage />)
    const parsed = (await screen.findAllByText('EURUSD CALL 60s'))[0]?.closest('tr') as HTMLElement
    expect(within(parsed).getByText('Parsed')).toBeInTheDocument()
    const chat = screen.getByText('good morning everyone').closest('tr') as HTMLElement
    expect(within(chat).getByText('Not parsed')).toBeInTheDocument()
    expect(within(chat).getByText('no direction in the message')).toBeInTheDocument()
    expect(screen.getByText(/chain active/)).toBeInTheDocument()
  })

  it('shows hostile message text as plain text, never as markup', async () => {
    const hostile = '<img src=x onerror="window.pwned=1"><script>window.pwned=1</script>'
    mockApi([GROUPS, ['GET', '/signals', json(page([makeSignal({ raw_text: hostile })]))]])
    const { container } = renderWith(<SignalsPage />)
    expect(await screen.findByText(hostile)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined()
  })

  it('has an empty state', async () => {
    mockApi([GROUPS, ['GET', '/signals', json(page([]))]])
    renderWith(<SignalsPage />)
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument()
  })

  it('filters by result and goes back to the first page', async () => {
    const api = mockApi([GROUPS, ['GET', '/signals', json(page([makeSignal()], { total: 120 }))]])
    const user = userEvent.setup()
    renderWith(<SignalsPage />)
    await screen.findAllByText('EURUSD CALL 60s')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.selectOptions(screen.getByLabelText('Result'), 'not_parsed')
    await vi.waitFor(() => {
      expect(api.calls.at(-1)?.path).toMatch(/status=not_parsed/)
    })
    expect(api.calls.at(-1)?.path).toContain('offset=0')
  })
})
