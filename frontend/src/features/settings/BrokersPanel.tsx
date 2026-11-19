import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import type { BrokerItem, BrokersOut } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { BROKER_LABEL } from '../../lib/brokers'
import { errorMessage } from '../../lib/errors'

const STATE: Record<BrokerItem['state'], { text: string; tone: Tone }> = {
  off: { text: 'switched off', tone: 'muted' },
  needs_you: { text: 'needs you', tone: 'bad' },
  connected: { text: 'connected', tone: 'good' },
  connecting: { text: 'connecting…', tone: 'warn' },
  reconnecting: { text: 'reconnecting…', tone: 'warn' },
  disconnected: { text: 'disconnected', tone: 'bad' },
  no_login: { text: 'no login stored', tone: 'muted' },
  engine_stopped: { text: 'engine stopped', tone: 'muted' },
}

function BrokerRow({ item }: { item: BrokerItem }) {
  const client = useQueryClient()
  const label = BROKER_LABEL[item.broker]
  const toggle = useMutation({
    mutationFn: () => api.brokers.set(item.broker, !item.enabled),
    onSuccess: (data) => {
      client.setQueryData(keys.brokers, data)
      void client.invalidateQueries({ queryKey: keys.status })
      void client.invalidateQueries({ queryKey: keys.health })
    },
  })
  const state = STATE[item.state]
  return (
    <li>
      <div className="secret-row">
        <span>
          <strong>{label}</strong> <Badge tone={state.tone}>{state.text}</Badge>
        </span>
        <Button
          disabled={toggle.isPending}
          onClick={() => {
            toggle.mutate()
          }}
        >
          {item.enabled ? `Switch ${label} off` : `Switch ${label} on`}
        </Button>
      </div>
      {item.detail !== null && item.detail !== undefined && (
        <p className="help" role="note">
          {item.detail}
        </p>
      )}
      {toggle.isError && (
        <p role="alert" className="form-error">
          {errorMessage(toggle.error)}
        </p>
      )}
    </li>
  )
}

/**
 * A switch per broker (decision D-81): an off broker is not connected and stops trying to log in;
 * what would trade on it is skipped, saying so. The choice is remembered across restarts.
 */
export function BrokersPanel({ data }: { data: BrokersOut }) {
  return (
    <fieldset>
      <legend>Brokers</legend>
      <p className="help">
        Switch off a broker you are not using: it stops connecting and logging in, and the other
        broker carries on. It cannot be switched off while it has open trades, running chains or a
        running session.
      </p>
      <ul className="secret-list">
        {data.items.map((item) => (
          <BrokerRow key={item.broker} item={item} />
        ))}
      </ul>
    </fieldset>
  )
}
