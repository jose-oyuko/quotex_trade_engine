// Owns the one WebSocket connection and turns it into cache updates:
//   snapshot -> replaces the cached status (and marks every list stale: events may have been missed)
//   events   -> patch the cached status, and mark the lists they touch stale
// Events are collected and applied once per animation frame, so a burst of events costs one
// render, not one per event.
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { keys } from '../api/queries'
import { LiveSocket, liveUrl, type LiveSocketOptions, type LiveStatus } from '../api/live'
import type { Snapshot } from '../api/types'
import { applyEvents, type LiveMessage } from './applyEvent'
import { LiveStatusContext } from './liveStatus'

type Controller = Pick<LiveSocket, 'start' | 'stop'>
export type CreateLive = (options: LiveSocketOptions) => Controller

const schedule: (callback: () => void) => void =
  typeof requestAnimationFrame === 'function'
    ? (callback) => {
        requestAnimationFrame(callback)
      }
    : (callback) => {
        setTimeout(callback, 16)
      }

/** The lists an event makes stale. */
function staleKeys(message: LiveMessage): (readonly unknown[])[] {
  switch (message.type) {
    case 'signal.received':
      return [keys.signals]
    case 'chain.started':
    case 'chain.advanced':
    case 'chain.ended':
      return [keys.chains, keys.groups]
    case 'trade.opened':
      return [keys.trades]
    case 'trade.settled':
      return [keys.trades, keys.risk]
    case 'risk.tripped':
      return [keys.riskEvents]
    case 'controls.changed':
      return [keys.groups, keys.risk]
    case 'balance.updated':
    case 'connection.changed':
    case 'account.changed':
      return []
  }
}

function invalidateEverything(client: QueryClient): void {
  for (const key of [
    keys.groups,
    keys.chains,
    keys.trades,
    keys.signals,
    keys.risk,
    keys.riskEvents,
  ]) {
    void client.invalidateQueries({ queryKey: key })
  }
}

export function LiveProvider({
  children,
  createLive = (options) => new LiveSocket(options),
  url = liveUrl(),
}: {
  children: ReactNode
  createLive?: CreateLive
  url?: string
}) {
  const client = useQueryClient()
  const [status, setStatus] = useState<LiveStatus>('connecting')
  const createRef = useRef(createLive)

  useEffect(() => {
    let pending: LiveMessage[] = []
    let scheduled = false
    let disposed = false

    const flush = () => {
      scheduled = false
      if (disposed || pending.length === 0) return
      const batch = pending
      pending = []
      client.setQueryData<Snapshot>(keys.status, (old) =>
        old === undefined ? old : applyEvents(old, batch),
      )
      const stale = new Map<string, readonly unknown[]>()
      for (const message of batch) {
        for (const key of staleKeys(message)) stale.set(JSON.stringify(key), key)
      }
      for (const key of stale.values()) void client.invalidateQueries({ queryKey: key })
    }

    const live = createRef.current({
      url,
      onStatus: setStatus,
      onMessage: (message) => {
        if (message.type === 'snapshot') {
          pending = [] // anything queued is older than this snapshot
          client.setQueryData<Snapshot>(keys.status, message.data)
          invalidateEverything(client)
          return
        }
        pending.push(message)
        if (!scheduled) {
          scheduled = true
          schedule(flush)
        }
      },
    })
    live.start()
    return () => {
      disposed = true
      live.stop()
    }
  }, [client, url])

  const value = useMemo(() => status, [status])
  return <LiveStatusContext.Provider value={value}>{children}</LiveStatusContext.Provider>
}
