import { createContext, useContext } from 'react'
import type { LiveStatus } from '../api/live'

export const LiveStatusContext = createContext<LiveStatus>('connecting')

/** Whether the live feed is connected: 'connecting', 'live', 'reconnecting' or 'stopped'. */
export function useLiveStatus(): LiveStatus {
  return useContext(LiveStatusContext)
}
