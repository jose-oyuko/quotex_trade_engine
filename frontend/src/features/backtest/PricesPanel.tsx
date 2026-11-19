import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { keys, usePriceDownloads, usePrices } from '../../api/queries'
import type { Download, PriceAsset } from '../../api/types'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DataState } from '../../components/DataState'
import { errorMessage } from '../../lib/errors'
import { isoDay } from './backtestSchema'

/** Assets worth downloading; any other Deriv symbol can be typed. */
const SUGGESTED_ASSETS = ['1HZ75V', 'R_75', '1HZ100V', 'R_100', '1HZ50V', 'R_50', 'EURUSD']

const STATE: Record<Download['state'], { text: string; tone: Tone }> = {
  running: { text: 'downloading', tone: 'info' },
  done: { text: 'done', tone: 'good' },
  failed: { text: 'failed', tone: 'bad' },
  cancelled: { text: 'cancelled', tone: 'muted' },
}

const when = (iso: string | null) =>
  iso === null ? '—' : new Date(iso).toISOString().slice(0, 16).replace('T', ' ')

function Running({ download }: { download: Download }) {
  const client = useQueryClient()
  const cancel = useMutation({
    mutationFn: () => api.prices.cancel(download.id),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.prices })
    },
  })
  const percent = Math.round(download.progress * 100)
  return (
    <div className="run-panel" aria-live="polite">
      <p>
        Downloading <strong>{download.asset}</strong> from {when(download.start)} to{' '}
        {when(download.end)} UTC: {download.ticks.toLocaleString()} new prices so far.
      </p>
      <progress max={100} value={percent} aria-label={`Download ${String(percent)}% done`}>
        {percent}%
      </progress>{' '}
      <span>{percent}%</span>{' '}
      <Button
        disabled={cancel.isPending}
        onClick={() => {
          cancel.mutate()
        }}
      >
        Cancel
      </Button>
      {cancel.isError && (
        <p role="alert" className="form-error">
          {errorMessage(cancel.error)}
        </p>
      )}
    </div>
  )
}

function DownloadForm({ busy }: { busy: boolean }) {
  const client = useQueryClient()
  const today = new Date()
  const [asset, setAsset] = useState('1HZ75V')
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 86_400_000)))
  const [end, setEnd] = useState(isoDay(today))
  const start_download = useMutation({
    mutationFn: () =>
      api.prices.download({
        asset: asset.trim(),
        start: `${start}T00:00:00Z`,
        end: `${end}T00:00:00Z`,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.prices })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    start_download.mutate()
  }
  return (
    <form className="filters" onSubmit={submit} aria-label="Download prices">
      <label>
        Asset
        <input
          list="price-assets"
          value={asset}
          onChange={(e) => {
            setAsset(e.target.value)
          }}
          required
        />
      </label>
      <datalist id="price-assets">
        {SUGGESTED_ASSETS.map((a) => (
          <option key={a} value={a} />
        ))}
      </datalist>
      <label>
        From (UTC)
        <input
          type="date"
          value={start}
          onChange={(e) => {
            setStart(e.target.value)
          }}
          required
        />
      </label>
      <label>
        To (UTC, 00:00)
        <input
          type="date"
          value={end}
          onChange={(e) => {
            setEnd(e.target.value)
          }}
          required
        />
      </label>
      <Button type="submit" variant="primary" disabled={busy || start_download.isPending}>
        Download
      </Button>
      {start_download.isError && (
        <p role="alert" className="form-error">
          {errorMessage(start_download.error)}
        </p>
      )}
    </form>
  )
}

function HeldAsset({ held }: { held: PriceAsset }) {
  const client = useQueryClient()
  const [asking, setAsking] = useState(false)
  const forget = useMutation({
    mutationFn: () => api.prices.forget(held.asset),
    onSuccess: () => {
      setAsking(false)
      void client.invalidateQueries({ queryKey: keys.prices })
    },
  })
  return (
    <tr>
      <th scope="row">{held.asset}</th>
      <td>{held.ticks.toLocaleString()}</td>
      <td>{when(held.first)}</td>
      <td>{when(held.last)}</td>
      <td>
        {held.ranges.map((r) => (
          <div key={r.start}>
            {when(r.start)} → {when(r.end)}
          </div>
        ))}
      </td>
      <td>
        <Button
          variant="quiet"
          onClick={() => {
            setAsking(true)
          }}
        >
          Delete
        </Button>
        {asking && (
          <ConfirmDialog
            title={`Delete the prices of ${held.asset}?`}
            confirmLabel="Delete"
            danger
            busy={forget.isPending}
            error={forget.isError ? errorMessage(forget.error) : null}
            onConfirm={() => {
              forget.mutate()
            }}
            onCancel={() => {
              setAsking(false)
            }}
          >
            <p>
              {held.ticks.toLocaleString()} stored prices go. Backtests already run keep their
              results.
            </p>
          </ConfirmDialog>
        )}
      </td>
    </tr>
  )
}

export function PricesPanel() {
  const prices = usePrices()
  const downloads = usePriceDownloads()
  const running = prices.data?.running ?? null
  return (
    <section aria-labelledby="prices-heading">
      <h2 id="prices-heading">Price history</h2>
      <p className="help">
        Past prices from Deriv's public price service: no login, nothing is traded. Deriv keeps
        about a year. A day of a 1-second index takes about a minute to download; parts already
        stored are skipped.
      </p>
      {running !== null && <Running download={running} />}
      <DownloadForm busy={running !== null} />
      <DataState
        query={prices}
        isEmpty={(data) => data.items.length === 0}
        empty="No prices stored yet: download some above."
      >
        {(data) => (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Stored prices</caption>
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  <th scope="col">Prices</th>
                  <th scope="col">Oldest (UTC)</th>
                  <th scope="col">Newest (UTC)</th>
                  <th scope="col">Periods downloaded</th>
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((held) => (
                  <HeldAsset key={held.asset} held={held} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DataState>
      {(downloads.data?.items.length ?? 0) > 0 && (
        <details>
          <summary>Recent downloads</summary>
          <ul className="plain-list">
            {downloads.data?.items.slice(0, 10).map((d) => (
              <li key={d.id}>
                <Badge tone={STATE[d.state].tone}>{STATE[d.state].text}</Badge> {d.asset},{' '}
                {when(d.start)} → {when(d.end)}: {d.ticks.toLocaleString()} new prices
                {d.note !== null && <span className="help"> {d.note}</span>}
                {d.error !== null && <span className="form-error"> {d.error}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
