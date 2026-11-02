import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { useStatus } from '../../api/queries'
import type { Chain } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { errorMessage } from '../../lib/errors'
import { titleCase } from '../../lib/format'
import { useGroupNames } from '../controls/useGroupNames'

function Direction({ value }: { value: 'call' | 'put' }) {
  return <Badge tone={value === 'call' ? 'good' : 'bad'}>{value.toUpperCase()}</Badge>
}

function Progress({ chain }: { chain: Chain }) {
  const total = chain.max_steps + 1 // the original trade plus every follow-up
  const current = Math.min(chain.step + 1, total)
  return (
    <div className="progress-cell">
      <progress
        value={current}
        max={total}
        aria-label={`Step ${String(current)} of ${String(total)}`}
      />
      <span>
        Step {current} of {total}
      </span>
    </div>
  )
}

/**
 * The chains that are running now, with their controls. "Stop after current" lets the open trade
 * settle and then ends the chain; "Skip to base" ends it at once so the group starts over at the
 * base stake with the next signal (asked about first: it cannot be undone).
 */
export function ChainsPanel({ chains }: { chains: Chain[] }) {
  const groupName = useGroupNames()
  const { data: status } = useStatus()
  const [stopping, setStopping] = useState<ReadonlySet<string>>(new Set())
  const [ending, setEnding] = useState<Chain | null>(null)

  const stop = useMutation({
    mutationFn: (chain: Chain) => api.chains.stopAfterCurrent(chain.id),
    onSuccess: (result) => {
      setStopping((old) => new Set(old).add(result.chain.id))
    },
  })
  const end = useMutation({
    mutationFn: (chain: Chain) => api.chains.end(chain.id),
    onSuccess: () => {
      setEnding(null)
    },
  })

  if (chains.length === 0) {
    return <p className="state-empty">No chains are running. They start when a signal arrives.</p>
  }

  return (
    <>
      {stop.isError && (
        <p role="alert" className="form-error">
          {errorMessage(stop.error)}
        </p>
      )}
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Chains running now</caption>
          <thead>
            <tr>
              <th scope="col">Group</th>
              <th scope="col">Asset</th>
              <th scope="col">Direction</th>
              <th scope="col">Strategy</th>
              <th scope="col">Progress</th>
              <th scope="col">Losses in a row</th>
              <th scope="col">Status</th>
              <th scope="col">Controls</th>
            </tr>
          </thead>
          <tbody>
            {chains.map((chain) => (
              <tr key={chain.id}>
                <td>{groupName(chain.group_id)}</td>
                <td>{chain.asset}</td>
                <td>
                  <Direction value={chain.origin_direction} />
                </td>
                <td>{titleCase(chain.strategy)}</td>
                <td>
                  <Progress chain={chain} />
                </td>
                <td>{chain.consecutive_losses}</td>
                <td>
                  <Badge tone="info">{titleCase(chain.status)}</Badge>
                  {stopping.has(chain.id) && <Badge tone="warn">stops after this trade</Badge>}
                </td>
                <td className="actions">
                  <Button
                    onClick={() => {
                      stop.mutate(chain)
                    }}
                    disabled={stopping.has(chain.id) || stop.isPending}
                    aria-label={`Stop after current trade: ${chain.asset}`}
                  >
                    Stop after current
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      setEnding(chain)
                    }}
                    aria-label={`Skip to base: ${chain.asset}`}
                  >
                    Skip to base…
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {ending !== null && (
        <ConfirmDialog
          title="Skip to base?"
          confirmLabel="Skip to base"
          danger
          busy={end.isPending}
          error={end.isError ? errorMessage(end.error) : null}
          onConfirm={() => {
            end.mutate(ending)
          }}
          onCancel={() => {
            setEnding(null)
            end.reset()
          }}
        >
          <p>
            End the {ending.asset} chain of <strong>{groupName(ending.group_id)}</strong> now, on
            the <strong>{(status?.account_type ?? ending.account_type).toUpperCase()}</strong>{' '}
            account. No further step will be placed, and the group's next signal starts again at the
            base stake of {ending.base_stake}. A trade that is already open still settles and is
            recorded.
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}
