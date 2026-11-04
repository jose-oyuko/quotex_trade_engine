import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { AuthGate } from '../features/auth/AuthGate'
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
      {/* The live connection is opened only after login: it needs the session too. */}
      <AuthGate>
        <LiveProvider {...(createLive ? { createLive } : {})}>{children}</LiveProvider>
      </AuthGate>
    </QueryClientProvider>
  )
}
