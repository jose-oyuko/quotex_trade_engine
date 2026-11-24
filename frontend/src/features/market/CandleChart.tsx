// The candlestick chart (TradingView Lightweight Charts, decision D-85): scroll and zoom with the
// mouse or touch, boxes over consolidations, shaded trends and breakout arrows. It runs inside the
// page and sends nothing anywhere. Times are UTC.
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'
import { ZonesPrimitive, type Zone } from './zones'

export interface ChartCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface ChartMarker {
  time: number
  direction: 'up' | 'down'
}

/** A backtest's pair, on the candle it opened in: what it made. */
export interface PairMarker {
  time: number
  result: 'won' | 'lost' | 'deep'
}

/** Show this stretch (and keep it shown until its candles have arrived). */
export interface ChartFocus {
  from: number
  to: number
  key: string
}

export interface CandleChartProps {
  candles: readonly ChartCandle[]
  length: number
  zones: readonly Zone[]
  markers: readonly ChartMarker[]
  pairs?: readonly PairMarker[]
  focus: ChartFocus | null
  /** The moments shown changed (scrolled, zoomed): the page loads candles around them. */
  onVisibleChange: (from: number, to: number) => void
  label: string
}

const NO_PAIRS: readonly PairMarker[] = []

function cssColour(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value === '' ? fallback : value
}

interface Parts {
  chart: IChartApi
  series: ISeriesApi<'Candlestick'>
  markers: ISeriesMarkersPluginApi<Time>
  zones: ZonesPrimitive
}

export function CandleChart({
  candles,
  length,
  zones,
  markers,
  pairs = NO_PAIRS,
  focus,
  onVisibleChange,
  label,
}: CandleChartProps) {
  const box = useRef<HTMLDivElement>(null)
  const parts = useRef<Parts | null>(null)
  const visible = useRef(onVisibleChange)
  const shown = useRef<string | null>(null)
  const drawn = useRef('')
  useEffect(() => {
    visible.current = onVisibleChange
  }, [onVisibleChange])

  useEffect(() => {
    const element = box.current
    if (element === null) return
    const text = cssColour('--text', '#1b1f27')
    const good = cssColour('--good', '#0a7a35')
    const bad = cssColour('--bad', '#b42318')
    const chart = createChart(element, {
      autoSize: true,
      layout: {
        background: { color: cssColour('--surface', '#ffffff') },
        textColor: text,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: cssColour('--surface-2', '#eef0f4') },
        horzLines: { color: cssColour('--surface-2', '#eef0f4') },
      },
      rightPriceScale: { borderColor: cssColour('--border', '#d5d9e0') },
      timeScale: { borderColor: cssColour('--border', '#d5d9e0'), timeVisible: true },
      localization: { locale: 'en-GB' },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: good,
      downColor: bad,
      wickUpColor: good,
      wickDownColor: bad,
      borderVisible: false,
    })
    const primitive = new ZonesPrimitive({
      consolidation: '#f59e0b', // amber: stands out from the green and red candles in both themes
      up: good,
      down: bad,
      selected: cssColour('--accent', '#1d5fd6'),
    })
    series.attachPrimitive(primitive)
    const markerApi = createSeriesMarkers(series, [])
    chart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (range !== null) visible.current(Number(range.from), Number(range.to))
    })
    parts.current = { chart, series, markers: markerApi, zones: primitive }
    return () => {
      parts.current = null
      shown.current = null
      drawn.current = ''
      chart.remove()
    }
  }, [])

  useEffect(() => {
    const p = parts.current
    if (p === null) return
    // the same candles again (a re-render): nothing to redraw
    const end = candles[candles.length - 1]
    const signature = `${String(candles.length)}:${String(candles[0]?.time)}:${String(end?.time)}:${String(end?.close)}`
    if (signature === drawn.current) return
    drawn.current = signature
    const scale = p.chart.timeScale()
    const before = candles.length > 0 ? scale.getVisibleRange() : null
    p.series.setData(
      candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    )
    // candles loaded before the ones shown must not move the view
    if (before !== null) scale.setVisibleRange(before)
  }, [candles])

  useEffect(() => {
    const p = parts.current
    if (p === null) return
    p.zones.setZones(
      zones,
      candles.map((c) => c.time),
    )
    const good = cssColour('--good', '#0a7a35')
    const bad = cssColour('--bad', '#b42318')
    p.markers.setMarkers(
      [
        ...markers.map((m) => ({
          time: m.time as UTCTimestamp,
          position: m.direction === 'up' ? ('belowBar' as const) : ('aboveBar' as const),
          shape: m.direction === 'up' ? ('arrowUp' as const) : ('arrowDown' as const),
          color: m.direction === 'up' ? good : bad,
        })),
        ...pairs.map((m) => ({
          time: m.time as UTCTimestamp,
          position: 'inBar' as const,
          shape: m.result === 'deep' ? ('square' as const) : ('circle' as const),
          color: m.result === 'won' ? good : bad,
          size: 0.6,
        })),
      ].sort((a, b) => a.time - b.time),
    )
  }, [zones, markers, pairs, candles])

  useEffect(() => {
    const p = parts.current
    if (p === null || focus === null || shown.current === focus.key) return
    const first = candles[0]
    const last = candles[candles.length - 1]
    // wait until the candles of that moment have arrived
    if (first === undefined || last === undefined) return
    if (first.time > focus.from || last.time < focus.from) return
    const pad = 20 * length
    p.chart.timeScale().setVisibleRange({
      from: (focus.from - pad) as UTCTimestamp,
      to: (focus.to + pad) as UTCTimestamp,
    })
    shown.current = focus.key
  }, [focus, candles, length])

  return <div ref={box} className="candle-chart" role="img" aria-label={label} />
}
