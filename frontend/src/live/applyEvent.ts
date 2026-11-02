// Applies one live message to the cached status. Pure and immutable: it returns the same object
// when the message changes nothing, so React re-renders only what really changed.
import type { Chain, ServerMessage, Snapshot, Trade } from '../api/types'

type Live = Exclude<ServerMessage, { type: 'snapshot' | 'heartbeat' }>

const ACTIVE_CHAIN: ReadonlySet<string> = new Set(['pending', 'open'])
const UNSETTLED_TRADE: ReadonlySet<string> = new Set(['pending', 'open'])

function upsert<T extends { id: string; created_at: string }>(
  items: T[],
  item: T,
  keep: boolean,
): T[] {
  const without = items.filter((existing) => existing.id !== item.id)
  if (!keep) return without.length === items.length ? items : without
  return [...without, item].sort((a, b) => a.created_at.localeCompare(b.created_at))
}

export function applyEvent(state: Snapshot, message: Live): Snapshot {
  switch (message.type) {
    case 'chain.started':
    case 'chain.advanced':
    case 'chain.ended': {
      const chain: Chain = message.data
      const open_chains = upsert(state.open_chains, chain, ACTIVE_CHAIN.has(chain.status))
      return open_chains === state.open_chains ? state : { ...state, open_chains }
    }
    case 'trade.opened':
    case 'trade.settled': {
      const trade: Trade = message.data
      const open_trades = upsert(state.open_trades, trade, UNSETTLED_TRADE.has(trade.status))
      return open_trades === state.open_trades ? state : { ...state, open_trades }
    }
    case 'balance.updated':
      // only the balance of the account in use is shown
      return message.data.account_type === state.account_type
        ? { ...state, balance: message.data }
        : state
    case 'connection.changed':
      return {
        ...state,
        connections: {
          ...state.connections,
          [message.data.component]: {
            connected: message.data.connected,
            detail: message.data.detail,
            since: message.at,
          },
        },
      }
    case 'account.changed':
      return {
        ...state,
        account_type: message.data.account_type,
        balance: state.balance?.account_type === message.data.account_type ? state.balance : null,
      }
    case 'controls.changed':
      return { ...state, controls: message.data }
    case 'signal.received':
    case 'risk.tripped':
      return state // shown in lists, which refetch; nothing in the status changes
  }
}

export function applyEvents(state: Snapshot, messages: Live[]): Snapshot {
  return messages.reduce(applyEvent, state)
}

export type LiveMessage = Live
