// Builders for the shapes the API returns, with sensible defaults: override only what a test cares about.
import type {
  Chain,
  Group,
  Page,
  ReportBreakdown,
  ReportDepth,
  ReportEquity,
  ReportMetrics,
  ReportSummary,
  Signal,
  Snapshot,
  Trade,
} from '../api/types'

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

export function makeMetrics(overrides: Partial<ReportMetrics> = {}): ReportMetrics {
  return {
    trades: 9,
    wins: 4,
    losses: 5,
    draws: 0,
    win_rate: 4 / 9,
    profit: '-2.50',
    staked: '19.00',
    roi: -2.5 / 19,
    avg_stake: '2.11',
    avg_payout_pct: 81.7,
    sample: 'tiny',
    ...overrides,
  }
}

const FILTER = {
  account_type: 'demo',
  since: null,
  until: null,
  group_id: null,
  strategy: null,
  asset: null,
  utc_offset_minutes: 0,
} as const

export function makeSummary(overrides: Partial<ReportSummary> = {}): ReportSummary {
  return {
    filter: FILTER,
    metrics: makeMetrics(),
    not_counted: { failed: 1, unknown: 1, open: 1 },
    streaks: { longest_win: 2, longest_loss: 4, current: 2 },
    drawdown: {
      max_amount: '9.00',
      peak_day: '2026-11-02',
      trough_day: '2026-11-03',
      current_amount: '3.90',
    },
    expectation: {
      breakeven_win_rate: 0.5505,
      actual_win_rate: 0.4444,
      edge: -0.106,
      z_score: -0.64,
      verdict: 'not_enough_data',
    },
    first_day: '2026-11-02',
    last_day: '2026-11-04',
    sample_guide: { tiny_below: 10, small_below: 30 },
    ...overrides,
  }
}

export function makeBreakdown(
  by: ReportBreakdown['by'],
  rows: [key: string, label: string, trades: number, profit: string][],
): ReportBreakdown {
  return {
    filter: FILTER,
    by,
    rows: rows.map(([key, label, trades, profit]) => ({
      key,
      label,
      metrics: makeMetrics({
        trades,
        wins: Math.round(trades / 2),
        losses: trades - Math.round(trades / 2),
        win_rate: trades ? Math.round(trades / 2) / trades : null,
        profit,
        sample: trades < 10 ? 'tiny' : trades < 30 ? 'small' : 'ok',
      }),
    })),
  }
}

export function makeEquity(): ReportEquity {
  return {
    filter: FILTER,
    points: [
      { day: '2026-11-02', trades: 3, profit: '1.40', cumulative: '1.40' },
      { day: '2026-11-03', trades: 4, profit: '-9.00', cumulative: '-7.60' },
      { day: '2026-11-04', trades: 2, profit: '5.10', cumulative: '-2.50' },
    ],
  }
}

export function makeDepth(): ReportDepth {
  const row = (step: number, reaching: number, share: number) => ({
    step,
    chains_reaching: reaching,
    share_of_chains: share,
    trades: reaching,
    wins: 1,
    losses: reaching - 1,
    staked: '10.00',
    profit: '-1.00',
    chains_ending_here: 1,
    chains_won_here: 1,
    chain_profit_ending_here: '0.60',
  })
  return {
    filter: FILTER,
    chains: 5,
    completed: 4,
    exhausted: 1,
    other: 0,
    avg_chain_profit: '-0.50',
    steps: [row(1, 5, 1), row(2, 3, 0.6), row(3, 1, 0.2)],
  }
}
