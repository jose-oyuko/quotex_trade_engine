import { describe, expect, it } from 'vitest'
import { makeChain, makeSnapshot, makeTrade, NOW } from '../test/fixtures'
import { applyEvent, applyEvents, type LiveMessage } from './applyEvent'

const at = '2026-11-02T10:00:05Z'
const message = <T extends LiveMessage>(m: Omit<T, 'seq' | 'at'>): T => ({ seq: 1, at, ...m }) as T

describe('applyEvent', () => {
  it('adds a chain when it starts, updates it as it advances, removes it when it ends', () => {
    const chain = makeChain({ status: 'pending' })
    let state = applyEvent(makeSnapshot(), message({ type: 'chain.started', data: chain }))
    expect(state.open_chains).toEqual([chain])

    const advanced = makeChain({ status: 'open', step: 1, consecutive_losses: 1 })
    state = applyEvent(state, message({ type: 'chain.advanced', data: advanced }))
    expect(state.open_chains).toEqual([advanced])

    state = applyEvent(
      state,
      message({ type: 'chain.ended', data: makeChain({ status: 'completed', ended_at: at }) }),
    )
    expect(state.open_chains).toEqual([])
  })

  it('keeps open chains in the order they started', () => {
    const first = makeChain({ id: 'a', created_at: '2026-11-02T10:00:00Z' })
    const second = makeChain({ id: 'b', created_at: '2026-11-02T10:00:09Z' })
    const state = applyEvents(makeSnapshot(), [
      message({ type: 'chain.started', data: second }),
      message({ type: 'chain.started', data: first }),
    ])
    expect(state.open_chains.map((c) => c.id)).toEqual(['a', 'b'])
  })

  it('shows a trade while it is unsettled and drops it once it has any result', () => {
    for (const final of ['won', 'lost', 'draw', 'failed', 'unknown'] as const) {
      const trade = makeTrade({ status: 'pending' })
      let state = applyEvent(makeSnapshot(), message({ type: 'trade.opened', data: trade }))
      state = applyEvent(
        state,
        message({ type: 'trade.opened', data: makeTrade({ status: 'open' }) }),
      )
      expect(state.open_trades).toHaveLength(1)
      state = applyEvent(
        state,
        message({ type: 'trade.settled', data: makeTrade({ status: final }) }),
      )
      expect(state.open_trades).toEqual([])
    }
  })

  it('returns the very same object when nothing changes, so nothing re-renders', () => {
    const state = makeSnapshot()
    const ended = message({ type: 'chain.ended', data: makeChain({ status: 'stopped' }) })
    expect(applyEvent(state, ended)).toBe(state) // it was not shown in the first place
    const settled = message({ type: 'trade.settled', data: makeTrade({ status: 'won' }) })
    expect(applyEvent(state, settled)).toBe(state)
    expect(
      applyEvent(
        state,
        message({
          type: 'signal.received',
          data: {
            id: 's',
            group_id: 1,
            telegram_message_id: 1,
            received_at: at,
            raw_text: 'x',
            status: 'not_parsed',
            reason: 'r',
            asset: null,
            direction: null,
            duration_s: null,
            entry_time: null,
          },
        }),
      ),
    ).toBe(state)
  })

  it('does not change the state it was given', () => {
    const state = makeSnapshot()
    const before = JSON.stringify(state)
    applyEvent(state, message({ type: 'chain.started', data: makeChain() }))
    expect(JSON.stringify(state)).toBe(before)
  })

  it('shows only the balance of the account in use', () => {
    const state = makeSnapshot()
    const real = { taken_at: at, account_type: 'real' as const, balance: '55.00' }
    expect(applyEvent(state, message({ type: 'balance.updated', data: real }))).toBe(state)
    const demo = { taken_at: at, account_type: 'demo' as const, balance: '999.15' }
    expect(
      applyEvent(state, message({ type: 'balance.updated', data: demo })).balance?.balance,
    ).toBe('999.15')
  })

  it('updates a connection with the time of the message', () => {
    const state = applyEvent(
      makeSnapshot(),
      message({
        type: 'connection.changed',
        data: { component: 'telegram', connected: false, detail: 'reconnecting' },
      }),
    )
    expect(state.connections.telegram).toEqual({
      connected: false,
      detail: 'reconnecting',
      since: at,
    })
    expect(state.connections.quotex?.connected).toBe(true) // the other one is untouched
  })

  it('follows a switch of account and forgets the other account’s balance', () => {
    const state = applyEvent(
      makeSnapshot(),
      message({ type: 'account.changed', data: { account_type: 'real' } }),
    )
    expect(state.account_type).toBe('real')
    expect(state.balance).toBeNull()
    const kept = applyEvent(
      makeSnapshot(),
      message({ type: 'account.changed', data: { account_type: 'demo' } }),
    )
    expect(kept.balance?.balance).toBe('1000.00')
  })

  it('replaces the controls', () => {
    const base = makeSnapshot()
    const controls = { ...base.controls, kill_switch: true, paused_groups: [2] }
    const state = applyEvent(base, message({ type: 'controls.changed', data: controls }))
    expect(state.controls.kill_switch).toBe(true)
    expect(state.controls.paused_groups).toEqual([2])
  })

  it('applies a batch in order', () => {
    const start = makeChain({ status: 'pending' })
    const state = applyEvents(makeSnapshot(), [
      message({ type: 'chain.started', data: start }),
      message({ type: 'chain.advanced', data: makeChain({ step: 2 }) }),
      message({ type: 'chain.ended', data: makeChain({ status: 'exhausted' }) }),
    ])
    expect(state.open_chains).toEqual([])
    expect(NOW).toBeTruthy()
  })
})
