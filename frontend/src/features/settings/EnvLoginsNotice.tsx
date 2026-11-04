import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { keys, useEnvLogins } from '../../api/queries'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'

/**
 * Logins that were typed into backend/.env in the old days. Says so, and moves them into the
 * encrypted store with one button. It never shows a value, and `.env` is not edited from here: once
 * they are stored the notice asks for the lines to be deleted.
 */
export function EnvLoginsNotice() {
  const client = useQueryClient()
  const logins = useEnvLogins()
  const move = useMutation({
    mutationFn: () => api.envLogins.move(),
    onSuccess: async (result) => {
      client.setQueryData(keys.envLogins, { items: result.items })
      await Promise.all(
        [keys.secrets, keys.engine, keys.telegramLogin].map((key) =>
          client.invalidateQueries({ queryKey: key }),
        ),
      )
    },
  })
  if (!logins.isSuccess) return null // a failure here must not get in the way of the page
  const inEnv = logins.data.items.filter((item) => item.in_env)
  const waiting = inEnv.filter((item) => !item.stored)
  const moved = inEnv.filter((item) => item.stored)
  if (inEnv.length === 0) return null

  return (
    <div className="notice" role="status">
      {waiting.length > 0 && (
        <>
          <p>
            <strong>Old logins found in backend/.env:</strong>{' '}
            {waiting.map((item) => item.label).join(', ')}. They still work, but they sit there in
            plain text. Move them into the encrypted store?
          </p>
          {move.isError && (
            <p role="alert" className="form-error">
              {errorMessage(move.error)}
            </p>
          )}
          <Button
            variant="primary"
            disabled={move.isPending}
            onClick={() => {
              move.mutate()
            }}
          >
            {move.isPending ? 'Moving…' : 'Move them into the encrypted store'}
          </Button>
        </>
      )}
      {waiting.length === 0 && moved.length > 0 && (
        <p>
          {move.isSuccess && move.data.imported.length > 0 ? 'Moved. ' : ''}
          These logins are stored now, so the copies in backend/.env are no longer used:{' '}
          {moved.map((item) => item.label).join(', ')}. You can delete those lines from the file (or
          run <code>npm run env:import</code>, which does it for you).
        </p>
      )}
    </div>
  )
}
