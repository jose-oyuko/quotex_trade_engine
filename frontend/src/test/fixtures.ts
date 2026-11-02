// Builders for the shapes the API returns, with sensible defaults: override only what a test cares about.
import type { Chain, Group, Page, Signal, Snapshot, Trade } from '../api/types'

export const NOW = '2026-11-02T10:00:00Z'

export function page<T>(items: T[], overrides: Partial<Page<T>> = {}): Page<T> {
  return { items, total: items.length, limit: 50, offset: 0, ...overrides }
}

export function makeSnapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    version: '0.1.0',
    environment: 'development',
    engine: { enabled: true, running: true },
    account_type: 'demo',
    real_trading_allowed: false,
    connections: {
      quotex: { connected: true, detail: 'connected', since: NOW },
      telegram: { connected: true, detail: null, since: NOW },
    },
    balance: { taken_at: NOW, account_type: 'demo', balance: '1000.00' },
    controls: {
      kill_switch: false,
      paused_groups: [],
      limits: {
        max_stake: null,
        max_concurrent_trades: null,
        max_exposure: null,
        max_chain_trades: null,
        daily_stop_loss: null,
        daily_profit_target: null,
        reset_timezone: 'UTC',
        reset_time: '00:00',
      },
      group_limits: {},
    },
    day: null,
    open_chains: [],
    open_trades: [],
    last_event_at: null,
    ...overrides,
  }
}

export function makeChain(overrides: Partial<Chain> = {}): Chain {
  return {
    id: 'chain-1',
    group_id: 1,
    signal_id: 'signal-1',
    asset: 'EURUSD',
    origin_direction: 'call',
    duration_s: 60,
    account_type: 'demo',
    strategy: 'martingale',
    status: 'open',
    step: 0,
    consecutive_losses: 0,
    max_steps: 3,
    base_stake: '1.00',
    multipliers: ['2.0', '2.5', '3.0'],
    created_at: NOW,
    updated_at: NOW,
    ended_at: null,
    end_reason: null,
    ...overrides,
  }
}

export function makeTrade(overrides: Partial<Trade> = {}): Trade {
  return {
    id: 'trade-1',
    chain_id: 'chain-1',
    group_id: 1,
    step: 0,
    asset: 'EURUSD',
    direction: 'call',
    duration_s: 60,
    stake: '1.00',
    account_type: 'demo',
    status: 'open',
    created_at: NOW,
    payout_pct: 85,
    profit: null,
    broker_order_id: 'order-1',
    opened_at: NOW,
    expires_at: '2026-11-02T10:01:00Z',
    settled_at: null,
    error: null,
    latency: { signal_to_order_ms: 0.4, decision_to_order_ms: 0.1, order_ack_ms: 120 },
    ...overrides,
  }
}

export function makeSignal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 'signal-1',
    group_id: 1,
    telegram_message_id: 1,
    received_at: NOW,
    raw_text: 'EURUSD CALL 1m',
    status: 'parsed',
    reason: null,
    asset: 'EURUSD',
    direction: 'call',
    duration_s: 60,
    entry_time: null,
    ...overrides,
  }
}

export function makeGroup(overrides: Partial<Group> = {}): Group {
  return {
    id: 1,
    telegram_chat_id: -1001,
    title: 'Alpha signals',
    enabled: true,
    created_at: NOW,
    updated_at: NOW,
    settings: {
      parser: 'legacy_v1',
      asset_suffix_mode: 'otc',
      timezone: 'UTC-3',
      strategy: 'martingale',
      base_stake: '1.00',
      max_steps: 3,
      multipliers: ['2.0', '2.5', '3.0'],
      min_payout_pct: 80,
      updated_at: NOW,
    },
    paused: false,
    active_chains: 0,
    ...overrides,
  }
}
