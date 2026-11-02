import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { LiveProvider, type CreateLive } from '../live/LiveProvider'
import { makeQueryClient } from './queryClient'

export function AppProviders({
  children,
  client,
  createLive,
}: {
  children: ReactNode
  client?: QueryClient
  createLive?: CreateLive
}) {
  const [own] = useState(makeQueryClient)
  return (
    <QueryClientProvider client={client ?? own}>
      <LiveProvider {...(createLive ? { createLive } : {})}>{children}</LiveProvider>
    </QueryClientProvider>
  )
}
