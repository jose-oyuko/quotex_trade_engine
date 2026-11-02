import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveSocket, liveUrl, type LiveStatus, type SocketLike } from './live'
import type { ServerMessage } from './types'

class FakeSocket implements SocketLike {
  static all: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: string[] = []
  closed = false

  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeSocket.all.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {
    this.closed = true
  }

  // --- what the server does ---
  open() {
    this.onopen?.()
  }
  say(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
  drop() {
    this.onclose?.()
  }
}

const AT = '2026-11-02T10:00:00Z'
const snapshot = (seq: number) => ({ type: 'snapshot', seq, at: AT, reason: 'connect', data: {} })
const event = (seq: number) => ({
  type: 'chain.advanced',
  seq,
  at: AT,
  data: { id: `c${String(seq)}` },
})
const heartbeat = (seq: number) => ({ type: 'heartbeat', seq, at: AT })

function setup(options: { random?: () => number; staleAfterMs?: number } = {}) {
  const messages: ServerMessage[] = []
  const statuses: LiveStatus[] = []
  const live = new LiveSocket({
    url: 'ws://test/ws',
    onMessage: (m) => messages.push(m),
    onStatus: (s) => statuses.push(s),
    createSocket: (url) => new FakeSocket(url),
    random: () => 1, // no jitter: delays are exactly the backoff
    ...options,
  })
  return { live, messages, statuses }
}

const current = () => FakeSocket.all[FakeSocket.all.length - 1] as FakeSocket
const seqs = (messages: ServerMessage[]) => messages.map((m) => m.seq)
const resyncs = (socket: FakeSocket) => socket.sent.filter((s) => s === '{"type":"resync"}').length

describe('LiveSocket', () => {
  beforeEach(() => {
    FakeSocket.all = []
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('connects to the given address and is live after the first snapshot', () => {
    const { live, statuses } = setup()
    live.start()
    expect(current().url).toBe('ws://test/ws')
    expect(statuses).toEqual(['connecting'])
    current().open()
    expect(statuses).toEqual(['connecting']) // an open socket is not yet a picture of the system
    current().say(snapshot(5))
    expect(statuses).toEqual(['connecting', 'live'])
  })

  it('passes on the snapshot and the events that follow it, in order', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(5))
    current().say(event(6))
    current().say(event(7))
    expect(seqs(messages)).toEqual([5, 6, 7])
    expect(messages.map((m) => m.type)).toEqual(['snapshot', 'chain.advanced', 'chain.advanced'])
  })

  it('ignores events that arrive before the snapshot', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(event(1))
    expect(messages).toEqual([])
    current().say(snapshot(1))
    current().say(event(2))
    expect(seqs(messages)).toEqual([1, 2])
  })

  it('does not pass on heartbeats, and ignores one that is up to date', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(3))
    current().say(heartbeat(3))
    current().say(heartbeat(2))
    expect(seqs(messages)).toEqual([3])
    expect(resyncs(current())).toBe(0)
  })

  it('asks for a new snapshot when a heartbeat shows it missed events', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(3))
    current().say(heartbeat(5))
    expect(resyncs(current())).toBe(1)
    current().say(heartbeat(5)) // still waiting: asking again would only repeat itself
    current().say(event(4)) // the very next number, but a snapshot is already on its way
    current().say(event(6))
    expect(resyncs(current())).toBe(1)
    expect(seqs(messages)).toEqual([3]) // events are ignored until the new snapshot arrives
    current().say(snapshot(6))
    current().say(event(7))
    expect(seqs(messages)).toEqual([3, 6, 7])
  })

  it('detects a gap in the numbers, asks for a snapshot and carries on from it', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(1))
    current().say(event(2))
    current().say(event(4)) // 3 never arrived
    expect(resyncs(current())).toBe(1)
    current().say(event(5))
    expect(seqs(messages)).toEqual([1, 2])
    current().say({ ...snapshot(5), reason: 'resync' })
    current().say(event(6))
    expect(seqs(messages)).toEqual([1, 2, 5, 6])
  })

  it('ignores an event it has already seen', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(1))
    current().say(event(2))
    current().say(event(2))
    current().say(event(1))
    expect(seqs(messages)).toEqual([1, 2])
    expect(resyncs(current())).toBe(0)
  })

  it('accepts a snapshot the server sends on its own because the client fell behind', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(1))
    current().say({ ...snapshot(40), reason: 'slow_consumer' })
    current().say(event(41))
    expect(seqs(messages)).toEqual([1, 40, 41])
  })

  it('lets the application ask for a snapshot by hand, once', () => {
    const { live } = setup()
    live.start()
    current().open()
    current().say(snapshot(1))
    live.resync()
    live.resync()
    expect(resyncs(current())).toBe(1)
  })

  it('ignores frames that are not part of the protocol', () => {
    const { live, messages } = setup()
    live.start()
    current().open()
    current().say(snapshot(1))
    current().onmessage?.({ data: 'not json' })
    current().onmessage?.({ data: new ArrayBuffer(4) })
    current().say({ type: 'who.knows', seq: 2 })
    current().say({ type: 'chain.advanced' }) // no number
    current().say([1, 2])
    current().say(event(2))
    expect(seqs(messages)).toEqual([1, 2])
  })

  it('reconnects with a growing delay, and starts over from a snapshot', () => {
    const { live, messages, statuses } = setup()
    live.start()
    current().open()
    current().say(snapshot(1))
    current().drop()
    expect(statuses.at(-1)).toBe('reconnecting')
    expect(FakeSocket.all).toHaveLength(1)

    vi.advanceTimersByTime(999)
    expect(FakeSocket.all).toHaveLength(1)
    vi.advanceTimersByTime(1) // 1 s
    expect(FakeSocket.all).toHaveLength(2)
    current().drop() // never opened: the next wait is longer
    vi.advanceTimersByTime(1_999)
    expect(FakeSocket.all).toHaveLength(2)
    vi.advanceTimersByTime(1) // 2 s
    expect(FakeSocket.all).toHaveLength(3)

    current().open()
    current().say(event(9)) // an event before the snapshot of the new connection: ignored
    current().say(snapshot(9))
    expect(statuses.at(-1)).toBe('live')
    expect(seqs(messages)).toEqual([1, 9])

    current().drop() // opening resets the backoff: back to 1 s
    vi.advanceTimersByTime(1_000)
    expect(FakeSocket.all).toHaveLength(4)
  })

  it('never waits longer than the maximum between attempts', () => {
    const { live } = setup()
    live.start()
    for (let i = 0; i < 8; i += 1) {
      current().drop()
      vi.advanceTimersByTime(15_000)
    }
    expect(FakeSocket.all).toHaveLength(9)
    current().drop()
    vi.advanceTimersByTime(14_999)
    expect(FakeSocket.all).toHaveLength(9)
    vi.advanceTimersByTime(1)
    expect(FakeSocket.all).toHaveLength(10)
  })

  it('adds jitter to the delay so many dashboards do not reconnect together', () => {
    const { live } = setup({ random: () => 0 })
    live.start()
    current().drop()
    vi.advanceTimersByTime(499)
    expect(FakeSocket.all).toHaveLength(1)
    vi.advanceTimersByTime(1) // half of the 1 s base
    expect(FakeSocket.all).toHaveLength(2)
  })

  it('gives up on a connection that has gone silent and reconnects', () => {
    const { live, statuses } = setup({ staleAfterMs: 5_000 })
    live.start()
    const first = current()
    first.open()
    first.say(snapshot(1))
    vi.advanceTimersByTime(4_000)
    first.say(heartbeat(1)) // any frame counts as life
    vi.advanceTimersByTime(4_000)
    expect(statuses.at(-1)).toBe('live')
    vi.advanceTimersByTime(1_000) // 5 s of silence
    expect(statuses.at(-1)).toBe('reconnecting')
    expect(first.closed).toBe(true)
    vi.advanceTimersByTime(1_000)
    expect(FakeSocket.all).toHaveLength(2)
  })

  it('stops for good: closes the socket and does not reconnect', () => {
    const { live, statuses } = setup()
    live.start()
    const socket = current()
    socket.open()
    socket.say(snapshot(1))
    live.stop()
    expect(socket.closed).toBe(true)
    expect(statuses.at(-1)).toBe('stopped')
    vi.advanceTimersByTime(120_000)
    expect(FakeSocket.all).toHaveLength(1)
    socket.drop() // a late close event from the old socket is ignored
    vi.advanceTimersByTime(120_000)
    expect(FakeSocket.all).toHaveLength(1)
  })

  it('does not reconnect after a stop that came during the wait', () => {
    const { live } = setup()
    live.start()
    current().drop()
    live.stop()
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.all).toHaveLength(1)
  })

  it('can be started again after it was stopped', () => {
    const { live } = setup()
    live.start()
    live.stop()
    live.start()
    expect(FakeSocket.all).toHaveLength(2)
  })
})

describe('liveUrl', () => {
  it('uses the page host, and wss on https', () => {
    expect(liveUrl({ protocol: 'http:', host: '127.0.0.1:5173' })).toBe('ws://127.0.0.1:5173/ws')
    expect(liveUrl({ protocol: 'https:', host: 'bot.example' })).toBe('wss://bot.example/ws')
  })
})
