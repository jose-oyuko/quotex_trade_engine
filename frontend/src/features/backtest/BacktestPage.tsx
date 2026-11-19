import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import { keys, useBacktests } from '../../api/queries'
import type { BacktestItem } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DataState } from '../../components/DataState'
import { errorMessage } from '../../lib/errors'
import { BacktestForm } from './BacktestForm'
import { BacktestResult } from './BacktestResult'
import { PricesPanel } from './PricesPanel'

const STATE: Record<BacktestItem['state'], { text: string; tone: Tone }> = {
  running: { text: 'running', tone: 'info' },
  done: { text: 'done', tone: 'good' },
  failed: { text: 'failed', tone: 'bad' },
  cancelled: { text: 'cancelled', tone: 'muted' },
}

function RunRow({
  item,
  selected,
  onOpen,
  onDeleted,
}: {
  item: BacktestItem
  selected: boolean
  onOpen: () => void
  onDeleted: () => void
}) {
  const client = useQueryClient()
  const [asking, setAsking] = useState(false)
  const cancel = useMutation({
    mutationFn: () => api.backtests.cancel(item.id),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.backtests })
    },
  })
  const remove = useMutation({
    mutationFn: () => api.backtests.remove(item.id),
    onSuccess: () => {
      setAsking(false)
      onDeleted()
      void client.invalidateQueries({ queryKey: keys.backtests })
    },
  })
  const state = STATE[item.state]
  return (
    <tr className={selected ? 'tab-active' : undefined}>
      <th scope="row">{item.name}</th>
      <td>
        <Badge tone={state.tone}>{state.text}</Badge>
        {item.state === 'running' && ` ${String(Math.round(item.progress * 100))}%`}
      </td>
      <td>{item.created_at.slice(0, 16).replace('T', ' ')}</td>
      <td className="actions-row">
        <Button onClick={onOpen} disabled={selected}>
          Open
        </Button>
        {item.state === 'running' ? (
          <Button
            disabled={cancel.isPending}
            onClick={() => {
              cancel.mutate()
            }}
          >
            Cancel
          </Button>
        ) : (
          <Button
            variant="quiet"
            onClick={() => {
              setAsking(true)
            }}
          >
            Delete
          </Button>
        )}
        {asking && (
          <ConfirmDialog
            title={`Delete the backtest “${item.name}”?`}
            confirmLabel="Delete"
            danger
            busy={remove.isPending}
            error={remove.isError ? errorMessage(remove.error) : null}
            onConfirm={() => {
              remove.mutate()
            }}
            onCancel={() => {
              setAsking(false)
            }}
          >
            <p>Its results and chains go; the stored prices stay.</p>
          </ConfirmDialog>
        )}
      </td>
    </tr>
  )
}

export default function BacktestPage() {
  const [params, setParams] = useSearchParams()
  const selected = Number(params.get('run') ?? '') || null
  const runs = useBacktests()
  const open = (id: number | null) => {
    setParams(id === null ? {} : { run: String(id) })
  }
  return (
    <>
      <div className="page-head">
        <h1>Backtest</h1>
      </div>
      <p className="lead">
        How would a strategy have done on Deriv's real past prices? Download prices, describe a
        session, and compare strategies side by side. Nothing is traded.
      </p>
      <PricesPanel />
      <BacktestForm
        onStarted={(backtest) => {
          open(backtest.id)
        }}
      />
      <section aria-labelledby="runs-heading">
        <h2 id="runs-heading">Backtests</h2>
        <DataState
          query={runs}
          isEmpty={(data) => data.items.length === 0}
          empty="No backtest yet."
        >
          {(data) => (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Backtests run</caption>
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">State</th>
                    <th scope="col">Started</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <RunRow
                      key={item.id}
                      item={item}
                      selected={item.id === selected}
                      onOpen={() => {
                        open(item.id)
                      }}
                      onDeleted={() => {
                        if (item.id === selected) open(null)
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </section>
      {selected !== null && <BacktestResult id={selected} />}
    </>
  )
}
