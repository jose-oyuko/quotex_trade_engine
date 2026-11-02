import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LiveSocketOptions } from '../api/live'
import { keys } from '../api/queries'
import type { Snapshot } from '../api/types'
import { makeChain, makeSnapshot, makeTrade } from '../test/fixtures'
import { LiveProvider, type CreateLive } from './LiveProvider'
import { useLiveStatus } from './liveStatus'

const AT = '2026-11-02T10:00:05Z'

/** A stand-in for the WebSocket client that lets the test play the server's part. */
function fakeLive() {
  const state: { options: LiveSocketOptions | null; started: number; stopped: number } = {
    options: null,
    started: 0,
    stopped: 0,
  }
  const create: CreateLive = (options) => {
    state.options = options
    return {
      start: () => {
        state.started += 1
      },
      stop: () => {
        state.stopped += 1
      },
    }
  }
  const send = (message: object) => {
    act(() => {
      state.options?.onMessage(message as never)
    })
  }
  return { state, create, send }
}

function Status() {
  return <p>feed: {useLiveStatus()}</p>
}

function setup(initial: Snapshot | null = makeSnapshot()) {
  const live = fakeLive()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (initial !== null) client.setQueryData(keys.status, initial)
  const view = render(
    <QueryClientProvider client={client}>
      <LiveProvider createLive={live.create} url="ws://test/ws">
        <Status />
      </LiveProvider>
    </QueryClientProvider>,
  )
  return { live, client, ...view }
}

const status = (client: QueryClient) => client.getQueryData<Snapshot>(keys.status)
const flushFrame = () => {
  act(() => {
    vi.advanceTimersByTime(20)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('LiveProvider', () => {
  it('connects to the given address once, and disconnects when it goes away', () => {
    const { live, unmount } = setup()
    expect(live.state.options?.url).toBe('ws://test/ws')
    expect(live.state.started).toBe(1)
    unmount()
    expect(live.state.stopped).toBe(1)
  })

  it('shows the state of the feed to the rest of the app', () => {
    const { live } = setup()
    expect(screen.getByText('feed: connecting')).toBeInTheDocument()
    act(() => {
      live.state.options?.onStatus?.('live')
    })
    expect(screen.getByText('feed: live')).toBeInTheDocument()
    act(() => {
      live.state.options?.onStatus?.('reconnecting')
    })
    expect(screen.getByText('feed: reconnecting')).toBeInTheDocument()
  })

  it('replaces the cached status with a snapshot, and marks the lists stale', () => {
    const { live, client } = setup(null)
    const spy = vi.spyOn(client, 'invalidateQueries')
    const snapshot = makeSnapshot({ open_chains: [makeChain()] })
    live.send({ type: 'snapshot', seq: 4, at: AT, reason: 'connect', data: snapshot })
    expect(status(client)).toEqual(snapshot)
    const invalidated = spy.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey))
    for (const key of [keys.groups, keys.chains, keys.trades, keys.signals, keys.risk]) {
      expect(invalidated).toContain(JSON.stringify(key))
    }
    expect(invalidated).not.toContain(JSON.stringify(keys.status)) // it was just set, not refetched
  })

  it('patches the status with events, once per frame, however many arrive', () => {
    const { live, client } = setup()
    const writes = vi.spyOn(client, 'setQueryData')
    live.send({
      type: 'chain.started',
      seq: 1,
      at: AT,
      data: makeChain({ id: 'a', status: 'pending' }),
    })
    live.send({ type: 'chain.advanced', seq: 2, at: AT, data: makeChain({ id: 'a', step: 1 }) })
    live.send({ type: 'trade.opened', seq: 3, at: AT, data: makeTrade() })
    expect(status(client)?.open_chains).toEqual([]) // nothing yet: collected for the next frame
    expect(writes).not.toHaveBeenCalled()

    flushFrame()
    expect(writes).toHaveBeenCalledTimes(1) // one update for the whole burst
    expect(status(client)?.open_chains.map((c) => c.step)).toEqual([1])
    expect(status(client)?.open_trades).toHaveLength(1)
  })

  it('marks only the lists an event touches as stale', () => {
    const { live, client } = setup()
    const spy = vi.spyOn(client, 'invalidateQueries')
    live.send({
      type: 'trade.settled',
      seq: 1,
      at: AT,
      data: makeTrade({ status: 'won', profit: '0.85' }),
    })
    flushFrame()
    const invalidated = spy.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey))
    expect(invalidated.sort()).toEqual(
      [JSON.stringify(keys.risk), JSON.stringify(keys.trades)].sort(),
    )
  })

  it('marks a list stale once, even when many events concern it', () => {
    const { live, client } = setup()
    const spy = vi.spyOn(client, 'invalidateQueries')
    for (let seq = 1; seq <= 10; seq += 1) {
      live.send({ type: 'trade.opened', seq, at: AT, data: makeTrade({ id: `t${String(seq)}` }) })
    }
    flushFrame()
    expect(spy).toHaveBeenCalledTimes(1)
    expect(status(client)?.open_trades).toHaveLength(10)
  })

  it('drops events that were waiting when a snapshot arrives: the snapshot is newer', () => {
    const { live, client } = setup()
    live.send({ type: 'chain.started', seq: 1, at: AT, data: makeChain({ id: 'old' }) })
    live.send({
      type: 'snapshot',
      seq: 9,
      at: AT,
      reason: 'resync',
      data: makeSnapshot({ open_chains: [makeChain({ id: 'new' })] }),
    })
    flushFrame()
    expect(status(client)?.open_chains.map((c) => c.id)).toEqual(['new'])
  })

  it('follows the controls and the account', () => {
    const { live, client } = setup()
    const controls = { ...makeSnapshot().controls, kill_switch: true }
    live.send({ type: 'controls.changed', seq: 1, at: AT, data: controls })
    live.send({ type: 'account.changed', seq: 2, at: AT, data: { account_type: 'real' } })
    flushFrame()
    expect(status(client)?.controls.kill_switch).toBe(true)
    expect(status(client)?.account_type).toBe('real')
  })

  it('ignores events until the first status exists, instead of inventing one', () => {
    const { live, client } = setup(null)
    live.send({ type: 'chain.started', seq: 1, at: AT, data: makeChain() })
    flushFrame()
    expect(status(client)).toBeUndefined()
  })

  it('does not apply events after it has been unmounted', () => {
    const { live, client, unmount } = setup()
    live.send({ type: 'chain.started', seq: 1, at: AT, data: makeChain() })
    unmount()
    flushFrame()
    expect(status(client)?.open_chains).toEqual([])
  })
})
