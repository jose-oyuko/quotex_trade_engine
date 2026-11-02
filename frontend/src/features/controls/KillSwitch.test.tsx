import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { keys } from '../../api/queries'
import type { Snapshot } from '../../api/types'
import { makeSnapshot } from '../../test/fixtures'
import { apiError, json, mockApi, renderWith, testClient } from '../../test/utils'
import { KillSwitch } from './KillSwitch'
import { vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
})

const engagedControls = (snapshot: Snapshot) => ({ ...snapshot.controls, kill_switch: true })
const releasedControls = (snapshot: Snapshot) => ({ ...snapshot.controls, kill_switch: false })

describe('the kill switch', () => {
  it('asks before it does anything, and nothing is sent until the owner confirms', async () => {
    const api = mockApi([])
    const user = userEvent.setup()
    renderWith(<KillSwitch />)

    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    const dialog = screen.getByRole('dialog', { name: 'Engage the kill switch?' })
    expect(dialog).toBeInTheDocument()
    expect(api.calls).toEqual([])

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.calls).toEqual([]) // cancelling changed nothing
    expect(screen.getByRole('button', { name: 'Kill switch…' })).toBeInTheDocument()
  })

  it('puts the safe choice in focus, so Enter alone cannot engage it', async () => {
    mockApi([])
    const user = userEvent.setup()
    renderWith(<KillSwitch />)
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('closes on Escape without engaging', async () => {
    const api = mockApi([])
    const user = userEvent.setup()
    renderWith(<KillSwitch />)
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.calls).toEqual([])
    expect(screen.getByRole('button', { name: 'Kill switch…' })).toHaveFocus() // back where it was
  })

  it('names the account it will stop: demo', async () => {
    mockApi([])
    const user = userEvent.setup()
    renderWith(<KillSwitch />)
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('DEMO')
  })

  it('names the account it will stop: real money', async () => {
    mockApi([])
    const user = userEvent.setup()
    renderWith(<KillSwitch />, { client: testClient(makeSnapshot({ account_type: 'real' })) })
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('REAL')
  })

  it('engages it when confirmed, and then shows that it is on', async () => {
    const snapshot = makeSnapshot()
    const api = mockApi([['POST', '/kill-switch', json(engagedControls(snapshot))]])
    const user = userEvent.setup()
    const { client } = renderWith(<KillSwitch />)

    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    await user.click(screen.getByRole('button', { name: 'Engage kill switch' }))

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(api.to('POST', '/kill-switch')).toHaveLength(1)
    expect(api.calls[0]?.body).toEqual({ stop_chains: false })
    expect(screen.getByText(/KILL SWITCH ON/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Release…' })).toBeInTheDocument()
    expect(client.getQueryData<Snapshot>(keys.status)?.controls.kill_switch).toBe(true)
  })

  it('can also end the running chains, when that box is ticked', async () => {
    const api = mockApi([['POST', '/kill-switch', json(engagedControls(makeSnapshot()))]])
    const user = userEvent.setup()
    renderWith(<KillSwitch />)
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    await user.click(screen.getByLabelText('Also end all running chains right now'))
    await user.click(screen.getByRole('button', { name: 'Engage kill switch' }))
    await waitFor(() => {
      expect(api.to('POST', '/kill-switch')).toHaveLength(1)
    })
    expect(api.calls[0]?.body).toEqual({ stop_chains: true })
  })

  it('keeps the dialog open and says why when the engine is not running', async () => {
    mockApi([
      [
        'POST',
        '/kill-switch',
        apiError(503, 'engine_not_running', 'The trading engine is not running.'),
      ],
    ])
    const user = userEvent.setup()
    renderWith(<KillSwitch />)
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    await user.click(screen.getByRole('button', { name: 'Engage kill switch' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The trading engine is not running.')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByText(/KILL SWITCH ON/)).not.toBeInTheDocument()
  })

  it('cannot be confirmed twice while the request is in flight', async () => {
    let resolve: (response: Response) => void = () => undefined
    const pending = new Promise<Response>((r) => {
      resolve = r
    })
    const api = mockApi([['POST', '/kill-switch', () => json({}) /* replaced below */]])
    vi.stubGlobal(
      'fetch',
      vi.fn(() => pending),
    )
    const user = userEvent.setup()
    renderWith(<KillSwitch />)
    await user.click(screen.getByRole('button', { name: 'Kill switch…' }))
    await user.click(screen.getByRole('button', { name: 'Engage kill switch' }))
    expect(await screen.findByRole('button', { name: 'Working…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    resolve(json(engagedControls(makeSnapshot())))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(api.calls).toEqual([])
  })

  it('shows the engaged state and asks before releasing it', async () => {
    const snapshot = makeSnapshot()
    snapshot.controls.kill_switch = true
    const api = mockApi([['DELETE', '/kill-switch', json(releasedControls(snapshot))]])
    const user = userEvent.setup()
    renderWith(<KillSwitch />, { client: testClient(snapshot) })

    expect(screen.queryByRole('button', { name: 'Kill switch…' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Release…' }))
    expect(screen.getByRole('dialog', { name: 'Release the kill switch?' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.calls).toEqual([])

    await user.click(screen.getByRole('button', { name: 'Release…' }))
    await user.click(screen.getByRole('button', { name: 'Release kill switch' }))
    await waitFor(() => {
      expect(api.to('DELETE', '/kill-switch')).toHaveLength(1)
    })
    expect(await screen.findByRole('button', { name: 'Kill switch…' })).toBeInTheDocument()
  })

  it('shows nothing until the status is known', () => {
    mockApi([])
    const { container } = renderWith(<KillSwitch />, { client: testClient(null) })
    expect(container).toBeEmptyDOMElement()
  })
})
