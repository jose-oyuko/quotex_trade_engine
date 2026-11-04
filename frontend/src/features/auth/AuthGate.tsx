import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, type ReactNode } from 'react'
import { api, onUnauthorized } from '../../api/client'
import { keys } from '../../api/queries'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'
import { AuthCard } from './AuthCard'
import { LoginPage } from './LoginPage'
import { SetupPage } from './SetupPage'

/**
 * Shows the dashboard only to a logged-in owner. Before that it shows the first-run setup page (no
 * account yet) or the login page. When the server later says the session is gone, the same question
 * is asked again and the login page takes over.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const state = useQuery({
    queryKey: keys.auth,
    queryFn: ({ signal }) => api.auth.state(signal),
    staleTime: Infinity,
    retry: false,
  })

  useEffect(
    () =>
      onUnauthorized(() => {
        void client.invalidateQueries({ queryKey: keys.auth })
      }),
    [client],
  )

  if (state.isPending) {
    return (
      <AuthCard title="Quotex Trade Engine">
        <p role="status">Loading…</p>
      </AuthCard>
    )
  }
  if (state.isError) {
    return (
      <AuthCard title="Quotex Trade Engine">
        <p role="alert" className="form-error">
          {errorMessage(state.error)}
        </p>
        <Button onClick={() => void state.refetch()}>Try again</Button>
      </AuthCard>
    )
  }
  if (state.data.authenticated) return <>{children}</>
  return state.data.setup_required ? <SetupPage /> : <LoginPage />
}
