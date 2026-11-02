import type { ReactNode } from 'react'
import { Button } from './Button'
import { Modal } from './Modal'

/**
 * Asks before something that cannot be undone. `children` must say what will happen (and on which
 * account); `error` shows why the last attempt failed. Cancel has focus first, so pressing Enter
 * straight away never confirms.
 */
export function ConfirmDialog({
  title,
  confirmLabel,
  danger = false,
  busy = false,
  error = null,
  onConfirm,
  onCancel,
  children,
}: {
  title: string
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
  children: ReactNode
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="modal-body">{children}</div>
      {error !== null && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <div className="modal-actions">
        <Button data-autofocus onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </Button>
      </div>
    </Modal>
  )
}
