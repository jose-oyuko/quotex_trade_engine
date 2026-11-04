import { useId, useState, type ReactNode } from 'react'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'

/**
 * Asks for the owner's password before something that moves money. The password is only sent with
 * this one request: it is not kept anywhere once the dialog closes.
 */
export function PasswordConfirm({
  title,
  confirmLabel,
  danger = false,
  busy,
  error,
  onSubmit,
  onCancel,
  children,
}: {
  title: string
  confirmLabel: string
  danger?: boolean
  busy: boolean
  error: unknown
  onSubmit: (password: string) => void
  onCancel: () => void
  children: ReactNode
}) {
  const id = useId()
  const [password, setPassword] = useState('')
  return (
    <ConfirmDialog
      title={title}
      confirmLabel={confirmLabel}
      danger={danger}
      busy={busy}
      error={error === null || error === undefined ? null : errorMessage(error)}
      onConfirm={() => {
        if (password !== '') onSubmit(password)
      }}
      onCancel={onCancel}
    >
      {children}
      <div className="field">
        <label htmlFor={id}>Your password</label>
        <input
          id={id}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => {
            setPassword(event.target.value)
          }}
        />
      </div>
    </ConfirmDialog>
  )
}
