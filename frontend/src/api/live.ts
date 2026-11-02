// The WebSocket client for /ws: it keeps one connection alive and hands the application a clean
// stream. The protocol is described in backend/app/api/schemas/ws.py:
//
//   - a `snapshot` replaces the whole picture, and comes first on every connection;
//   - events then arrive numbered 1 apart; a jump means something was missed, so the client asks
//     for a new snapshot (`resync`) and ignores events until it arrives;
//   - heartbeats carry the latest number, so even a quiet connection reveals that it is behind;
//   - if nothing at all arrives for a while the connection is considered dead and reopened.
//
// Only snapshots and events are passed on. Nothing here knows about React or the Query cache.
import type { ClientMessage, ServerMessage } from './types'

export type LiveStatus = 'connecting' | 'live' | 'reconnecting' | 'stopped'

/** The part of the browser's WebSocket that is used (so tests can supply a fake). */
export interface SocketLike {
  onopen: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  send(data: string): void
  close(): void
}

export interface LiveSocketOptions {
  url: string
  /** Called for every snapshot and every event, in order. Heartbeats are not passed on. */
  onMessage: (message: Exclude<ServerMessage, { type: 'heartbeat' }>) => void
  onStatus?: (status: LiveStatus) => void
  createSocket?: (url: string) => SocketLike
  /** Without any frame for this long the connection is dropped and reopened. */
  staleAfterMs?: number
  reconnectMs?: { initial: number; max: number }
  random?: () => number
}

const MESSAGE_TYPES: Record<ServerMessage['type'], true> = {
  snapshot: true,
  heartbeat: true,
  'signal.received': true,
  'chain.started': true,
  'chain.advanced': true,
  'chain.ended': true,
  'trade.opened': true,
  'trade.settled': true,
  'risk.tripped': true,
  'balance.updated': true,
  'connection.changed': true,
  'account.changed': true,
  'controls.changed': true,
}

function parse(data: unknown): ServerMessage | null {
  if (typeof data !== 'string') return null
  let value: unknown
  try {
    value = JSON.parse(data)
  } catch {
    return null
  }
  if (typeof value !== 'object' || value === null) return null
  const { type, seq } = value as Record<string, unknown>
  if (typeof type !== 'string' || !(type in MESSAGE_TYPES) || typeof seq !== 'number') return null
  return value as ServerMessage
}

/** `ws://` or `wss://` plus the page's own host: the dashboard always talks to its own server. */
export function liveUrl(location: Pick<Location, 'protocol' | 'host'> = window.location): string {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
}

export class LiveSocket {
  private readonly options: Required<Omit<LiveSocketOptions, 'onStatus'>> &
    Pick<LiveSocketOptions, 'onStatus'>
  private socket: SocketLike | null = null
  private lastSeq: number | null = null
  private resyncPending = false
  private attempt = 0
  private stopped = true
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private watchdog: ReturnType<typeof setTimeout> | null = null
  private status: LiveStatus = 'stopped'

  constructor(options: LiveSocketOptions) {
    this.options = {
      createSocket: (url) => new WebSocket(url) as unknown as SocketLike,
      staleAfterMs: 40_000,
      reconnectMs: { initial: 1_000, max: 15_000 },
      random: Math.random,
      ...options,
    }
  }

  start(): void {
    if (!this.stopped) return
    this.stopped = false
    this.attempt = 0
    this.open('connecting')
  }

  stop(): void {
    this.stopped = true
    this.clearTimers()
    this.detach()
    this.setStatus('stopped')
  }

  /** Asks the server for a fresh snapshot (used when the application suspects it is out of step). */
  resync(): void {
    if (this.resyncPending || this.socket === null) return
    this.resyncPending = true
    this.send({ type: 'resync' })
  }

  // --- connection ---

  private open(status: LiveStatus): void {
    this.setStatus(status)
    const socket = this.options.createSocket(this.options.url)
    this.socket = socket
    socket.onopen = () => {
      this.attempt = 0
      this.lastSeq = null // the snapshot that follows replaces everything
      this.resyncPending = false
      this.armWatchdog()
    }
    socket.onmessage = (event) => {
      this.armWatchdog()
      const message = parse(event.data)
      if (message !== null) this.handle(message)
    }
    socket.onclose = () => {
      if (this.socket === socket) this.lost()
    }
    socket.onerror = () => {
      // an error is always followed by a close event, which does the work
    }
  }

  private handle(message: ServerMessage): void {
    if (message.type === 'snapshot') {
      this.lastSeq = message.seq
      this.resyncPending = false
      this.setStatus('live')
      this.options.onMessage(message)
      return
    }
    if (this.lastSeq === null || this.resyncPending) return // waiting for a snapshot
    if (message.type === 'heartbeat') {
      if (message.seq > this.lastSeq) this.resync() // quiet, but behind
      return
    }
    if (message.seq === this.lastSeq + 1) {
      this.lastSeq = message.seq
      this.options.onMessage(message)
    } else if (message.seq > this.lastSeq) {
      this.resync() // a gap: something was missed
    } // else: already seen
  }

  private lost(): void {
    this.detach()
    this.setStatus('reconnecting')
    const { initial, max } = this.options.reconnectMs
    const base = Math.min(max, initial * 2 ** this.attempt)
    this.attempt += 1
    const delay = Math.round(base * (0.5 + this.options.random() / 2))
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (!this.stopped) this.open('reconnecting')
    }, delay)
  }

  private armWatchdog(): void {
    if (this.watchdog !== null) clearTimeout(this.watchdog)
    this.watchdog = setTimeout(() => {
      this.watchdog = null
      if (this.socket !== null) this.lost() // nothing heard for too long: the connection is dead
    }, this.options.staleAfterMs)
  }

  private detach(): void {
    const socket = this.socket
    this.socket = null
    if (this.watchdog !== null) clearTimeout(this.watchdog)
    this.watchdog = null
    this.lastSeq = null
    this.resyncPending = false
    if (socket === null) return
    socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null
    try {
      socket.close()
    } catch {
      // already closed
    }
  }

  private clearTimers(): void {
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  private send(message: ClientMessage): void {
    try {
      this.socket?.send(JSON.stringify(message))
    } catch {
      // the connection is closing; the close handler reconnects
    }
  }

  private setStatus(status: LiveStatus): void {
    if (this.status === status) return
    this.status = status
    this.options.onStatus?.(status)
  }
}
