import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { keys, useStatus } from '../../api/queries'
import type { Snapshot } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'

type Asking = 'engage' | 'release' | null

/**
 * The kill switch: always in reach, never one click. Engaging it asks first and says which account
 * it applies to; so does releasing it, because that lets orders flow again.
 */
export function KillSwitch() {
  const { data: status } = useStatus()
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState<Asking>(null)
  const [stopChains, setStopChains] = useState(false)

  const change = useMutation({
    mutationFn: (action: Exclude<Asking, null>) =>
      action === 'engage' ? api.killSwitch.engage(stopChains) : api.killSwitch.release(),
    onSuccess: (controls) => {
      queryClient.setQueryData<Snapshot>(keys.status, (old) => old && { ...old, controls })
      void queryClient.invalidateQueries({ queryKey: keys.chains })
      close()
    },
  })

  function close() {
    setAsking(null)
    setStopChains(false)
    change.reset()
  }

  if (status === undefined) return null
  const account = status.account_type.toUpperCase()
  const engaged = status.controls.kill_switch

  return (
    <>
      {engaged ? (
        <span className="killswitch-on">
          <Badge tone="bad">KILL SWITCH ON: no orders are sent</Badge>
          <Button
            onClick={() => {
              setAsking('release')
            }}
          >
            Release…
          </Button>
        </span>
      ) : (
        <Button
          variant="danger"
          onClick={() => {
            setAsking('engage')
          }}
        >
          Kill switch…
        </Button>
      )}

      {asking === 'engage' && (
        <ConfirmDialog
          title="Engage the kill switch?"
          confirmLabel="Engage kill switch"
          danger
          busy={change.isPending}
          error={change.isError ? errorMessage(change.error) : null}
          onConfirm={() => {
            change.mutate('engage')
          }}
          onCancel={close}
        >
          <p>
            This stops all trading on the <strong>{account}</strong> account. No new order is sent,
            including the next step of chains that are running; those chains end when their next
            order is refused. Trades that are already open still settle.
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={stopChains}
              onChange={(event) => {
                setStopChains(event.target.checked)
              }}
            />
            Also end all running chains right now
          </label>
        </ConfirmDialog>
      )}

      {asking === 'release' && (
        <ConfirmDialog
          title="Release the kill switch?"
          confirmLabel="Release kill switch"
          busy={change.isPending}
          error={change.isError ? errorMessage(change.error) : null}
          onConfirm={() => {
            change.mutate('release')
          }}
          onCancel={close}
        >
          <p>
            Orders can go out again on the <strong>{account}</strong> account: new signals will be
            traded.
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}
