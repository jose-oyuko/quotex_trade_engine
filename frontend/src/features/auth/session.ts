import type { QueryClient } from '@tanstack/react-query'
import { keys } from '../../api/queries'
import type { AuthState, AuthUser } from '../../api/types'

/**
 * Switches the app to a new login state. Everything fetched under the old one is forgotten (the next
 * visitor must not see it), except the login state itself: it is being watched, and clearing it
 * would cut the gate off from the answer.
 */
export function setLoginState(client: QueryClient, user: AuthUser | null): void {
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== keys.auth[0] })
  const state: AuthState = { setup_required: false, authenticated: user !== null, user }
  client.setQueryData(keys.auth, state)
}
