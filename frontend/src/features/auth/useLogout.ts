import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { setLoginState } from './session'

/** Ends this browser's session, forgets everything fetched with it, and shows the login page. */
export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.auth.logout(),
    onSettled: () => {
      setLoginState(client, null)
    },
  })
}
