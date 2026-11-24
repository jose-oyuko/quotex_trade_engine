// The Market page (decision D-85): the stored prices as candles, and the consolidations, breakouts
// and trends the engine finds in them, so the owner can check by eye that it sees what they mean.
// Everything marked on the chart comes from the server's scan; nothing is worked out again here.
import { useMutation, useQueries, type UseQueryResult } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { keys, useAssetNames, useMarketPatterns, usePrices } from '../../api/queries'
import type { Candles, Scan, Trend } from '../../api/types'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'
import { assetLabel } from '../backtest/assetNames'
import { CandleChart, type ChartCandle, type ChartFocus, type ChartMarker } from './CandleChart'
import { FoundList } from './FoundList'
import {
  TIMEFRAMES,
  chunkSpan,
  chunksAround,
  emptyScan,
  epochOf,
  epochOfInput,
  inputOf,
  isoOf,
  lengthLabel,
  statsText,
  toScanInput,
  trendAfter,
  type ScanFormValues,
} from './marketSchema'
import { ScanForm } from './ScanForm'
import type { Zone } from './zones'

interface View {
  key: string
  chunks: number[]
  focus: ChartFocus | null
}

/** The loaded chunks as one run of candles, oldest first. */
function mergeCandles(results: UseQueryResult<Candles>[]) {
  const byTime = new Map<number, ChartCandle>()
  for (const r of results) {
    for (const c of r.data?.items ?? []) {
      byTime.set(epochOf(c.start), {
        time: epochOf(c.start),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })
    }
  }
  return {
    candles: [...byTime.values()].sort((a, b) => a.time - b.time),
    loading: results.some((r) => r.isPending),
    error: results.find((r) => r.isError)?.error ?? null,
  }
}

function marks(scan: Scan | undefined, selected: number | null, length: number) {
  const zones: Zone[] = []
  const markers: ChartMarker[] = []
  if (scan === undefined) return { zones, markers }
  scan.trends.forEach((t) => {
    zones.push({
      from: epochOf(t.start),
      to: epochOf(t.end),
      top: null,
      bottom: null,
      kind: t.direction,
      selected: false,
    })
  })
  scan.consolidations.forEach((c, i) => {
    zones.push({
      from: epochOf(c.first),
      to: epochOf(c.end),
      top: c.high,
      bottom: c.low,
      kind: 'consolidation',
      selected: i === selected,
      label: `Consolidation · ${String(c.candles)} candles`,
    })
    // an arrow on the candle that confirmed the breakout (on the scan's own timeframe)
    if (c.breakout && scan.length === length) {
      markers.push({
        time: epochOf(c.breakout.known) - scan.length,
        direction: c.breakout.direction,
      })
    }
  })
  return { zones, markers }
}

export default function MarketPage() {
  const prices = usePrices()
  const names = useAssetNames().data?.items ?? []
  const patterns = useMarketPatterns().data?.items ?? []
  const held = prices.data?.items ?? []
  const [picked, setPicked] = useState('')
  const asset = picked || (held[0]?.asset ?? '')
  const [length, setLength] = useState(60)
  const [custom, setCustom] = useState('')
  const holding = held.find((h) => h.asset === asset)
  const last = holding?.last ? epochOf(holding.last) : null

  // which candles are loaded, and what the chart was asked to show, per asset and timeframe
  const viewKey = `${asset}:${String(length)}`
  const [view, setView] = useState<View | null>(null)
  const start: View = {
    key: viewKey,
    chunks: last === null ? [] : chunksAround(last - 200 * length, last, length),
    focus: last === null ? null : { from: last - 150 * length, to: last, key: `start:${viewKey}` },
  }
  const current = view?.key === viewKey ? view : start
  const need = (from: number, to: number, focus?: ChartFocus) => {
    setView((v) => {
      const base = v?.key === viewKey ? v : start
      const missing = chunksAround(from, to, length).filter((c) => !base.chunks.includes(c))
      if (missing.length === 0 && focus === undefined) return v
      return {
        key: viewKey,
        chunks: [...base.chunks, ...missing],
        focus: focus ?? base.focus,
      }
    })
  }

  const loaded = useQueries({
    queries: current.chunks.map((chunk) => {
      const [from, to] = chunkSpan(chunk, length)
      return {
        queryKey: [...keys.market, 'candles', asset, length, chunk],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          api.market.candles({ asset, start: isoOf(from), end: isoOf(to), length }, signal),
        staleTime: 60_000,
        enabled: asset !== '',
      }
    }),
    combine: mergeCandles,
  })

  const [jump, setJump] = useState('')
  const focusCount = useRef(0)
  const [form, setForm] = useState<ScanFormValues | null>(null)
  const values = form ?? emptyScan(last)
  const [selected, setSelected] = useState<number | null>(null)
  const scan = useMutation({
    mutationFn: () => api.market.scan(toScanInput(asset, length, values)),
    onSuccess: () => {
      setSelected(null)
    },
  })
  // scan by itself when the page opens and when the asset or timeframe changes, so the rectangles
  // are there without pressing Scan (with the definition in the form)
  const { mutate } = scan
  const autoScanned = useRef('')
  useEffect(() => {
    if (asset === '' || last === null || autoScanned.current === viewKey) return
    autoScanned.current = viewKey
    mutate()
  }, [asset, last, viewKey, mutate])
  const result = scan.data
  const { zones, markers } = marks(result, selected, length)
  const trends = result ? trendAfter(result) : new Map<number, Trend>()

  if (prices.isSuccess && held.length === 0) {
    return (
      <>
        <h1>Market</h1>
        <p className="state-empty">
          No prices are stored yet. Download some on the <Link to="/backtest">Backtest</Link> page
          first (a week of Volatility 75 (1s) is a good start).
        </p>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <h1>Market</h1>
      </div>
      <p className="lead">
        The stored prices as candles, with the consolidations and trends the engine finds. Check
        that it sees them the way you do. Nothing is traded.
      </p>
      <div className="filters">
        <label>
          Asset{' '}
          <select
            value={asset}
            onChange={(e) => {
              setPicked(e.target.value)
              setForm(null)
            }}
          >
            {held.map((h) => (
              <option key={h.asset} value={h.asset}>
                {assetLabel(h.asset, names)}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="days">
          <legend>Timeframe</legend>
          {TIMEFRAMES.map((t) => (
            <Button
              key={t.value}
              aria-pressed={length === t.value}
              onClick={() => {
                setLength(t.value)
              }}
            >
              {t.label}
            </Button>
          ))}
          <label>
            or seconds{' '}
            <input
              size={5}
              inputMode="numeric"
              value={custom}
              onChange={(e) => {
                setCustom(e.target.value)
              }}
            />
          </label>
          <Button
            onClick={() => {
              const seconds = Number(custom)
              if (Number.isInteger(seconds) && seconds >= 1 && seconds <= 86_400) setLength(seconds)
            }}
          >
            Use
          </Button>
        </fieldset>
        <label>
          Go to (UTC){' '}
          <input
            type="datetime-local"
            value={jump}
            onChange={(e) => {
              setJump(e.target.value)
            }}
          />
        </label>
        <Button
          onClick={() => {
            const at = epochOfInput(jump)
            if (at === null) return
            need(at - 100 * length, at + 100 * length, {
              from: at,
              to: at + 60 * length,
              key: `jump:${String(at)}:${String(++focusCount.current)}`,
            })
          }}
        >
          Go
        </Button>
      </div>
      <p className="help">
        {holding ? `${assetLabel(asset, names)}: ` : ''}
        {lengthLabel(length)} candles. Drag to scroll, wheel or pinch to zoom.
        {holding?.first && holding.last
          ? ` Stored from ${inputOf(epochOf(holding.first)).replace('T', ' ')} to ${inputOf(
              epochOf(holding.last),
            ).replace('T', ' ')} UTC.`
          : ''}
        {loaded.loading ? ' Loading candles…' : ''}
      </p>
      {loaded.error !== null && <p className="form-error">{errorMessage(loaded.error)}</p>}
      <CandleChart
        candles={loaded.candles}
        length={length}
        zones={zones}
        markers={markers}
        focus={current.focus}
        onVisibleChange={(from, to) => {
          need(from, to)
        }}
        label={`${lengthLabel(length)} candles of ${asset}, with the consolidations found marked as boxes`}
      />
      <p className="help">
        Amber rectangles: consolidations, from their range’s low to its high, labelled with their
        candles (the one chosen in the list is outlined in blue). Arrows: breakouts. Green or red
        shading: the trend after a breakout, up or down, until the next consolidation.
      </p>
      <ScanForm
        values={values}
        onChange={setForm}
        defaults={patterns}
        busy={scan.isPending}
        onScan={() => {
          scan.mutate()
        }}
      />
      {scan.isError && <p className="form-error">{errorMessage(scan.error)}</p>}
      {result && (
        <section aria-labelledby="found-heading">
          <h2 id="found-heading">What the scan found</h2>
          {result.length !== length && (
            <p className="notice">
              These were found on {lengthLabel(result.length)} candles; the chart shows{' '}
              {lengthLabel(length)}. Scan again to see this timeframe’s.
            </p>
          )}
          <ul className="plain-list">
            {statsText(result.stats, result.length).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <FoundList
            scan={result}
            selected={selected}
            onShow={(i) => {
              const c = result.consolidations[i]
              if (c === undefined) return
              setSelected(i)
              const from = epochOf(c.first)
              const to = epochOf(trends.get(i)?.end ?? c.end)
              need(from - 50 * length, to + 50 * length, {
                from,
                to,
                key: `found:${String(i)}:${String(++focusCount.current)}`,
              })
            }}
          />
        </section>
      )}
    </>
  )
}
