// Rectangles and shaded stretches drawn under the candles (decision D-85): a consolidation is an
// outlined rectangle from its range's low to its high, labelled; a trend a band over the whole height. A "series primitive" is the
// chart library's way to draw one's own shapes; the geometry is plain functions, tested on their own.
import type {
  IChartApiBase,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
} from 'lightweight-charts'

export type ZoneKind = 'consolidation' | 'up' | 'down'

export interface Zone {
  /** Epoch seconds: the first candle's start, and the end (the next candle's start). */
  from: number
  to: number
  /** The price range of a rectangle; null for a band over the whole height. */
  top: number | null
  bottom: number | null
  kind: ZoneKind
  selected: boolean
  /** Written above a rectangle: "Consolidation · 8 candles". */
  label?: string
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
  kind: ZoneKind
  selected: boolean
  label?: string
}

export interface ZoneColours {
  consolidation: string
  up: string
  down: string
  selected: string
}

/** A rectangle reaches a little beyond the range, so its outline does not hide the wick tips. */
export const PAD_PX = 3

/** The position of a moment among the candles, in the chart's "logical" units: candle `i` sits at
 * `i`, so the edge before it is `i - 0.5`. A moment after the last candle lands past its end. */
export function logicalOf(times: readonly number[], epoch: number): number {
  let lo = 0
  let hi = times.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if ((times[mid] ?? 0) < epoch) lo = mid + 1
    else hi = mid
  }
  return lo - 0.5
}

/**
 * The pixel position of an edge between candles (`i - 0.5`). The chart only converts whole candle
 * positions (anything in between gives 0), so the edge is taken half a candle before candle `i`.
 */
export function edgeX(at: (index: number) => number | null, logical: number): number | null {
  const index = Math.round(logical + 0.5)
  const here = at(index)
  const next = at(index + 1)
  if (here === null || next === null) return null
  return here - (next - here) / 2
}

/** Where each zone is drawn, in pixels; zones without width are left out. */
export function zoneRects(
  zones: readonly Zone[],
  times: readonly number[],
  x: (logical: number) => number | null,
  y: (price: number) => number | null,
  height: number,
): Rect[] {
  const rects: Rect[] = []
  for (const zone of zones) {
    const left = x(logicalOf(times, zone.from))
    const right = x(logicalOf(times, zone.to))
    if (left === null || right === null || right <= left) continue
    let top = 0
    let bottom = height
    if (zone.top !== null && zone.bottom !== null) {
      const high = y(zone.top)
      const low = y(zone.bottom)
      if (high === null || low === null) continue
      top = Math.min(high, low) - PAD_PX
      bottom = Math.max(high, low) + PAD_PX
    }
    rects.push({
      x: left,
      y: top,
      width: right - left,
      height: Math.max(bottom - top, 1),
      kind: zone.kind,
      selected: zone.selected,
      ...(zone.label === undefined ? {} : { label: zone.label }),
    })
  }
  return rects
}

type DrawTarget = Parameters<IPrimitivePaneRenderer['draw']>[0]

export class ZonesPrimitive implements ISeriesPrimitive {
  private chart: IChartApiBase | null = null
  private series: ISeriesApi<SeriesType> | null = null
  private requestUpdate: (() => void) | null = null
  private zones: readonly Zone[] = []
  private times: readonly number[] = []
  private readonly views: readonly IPrimitivePaneView[]
  private readonly colours: ZoneColours

  constructor(colours: ZoneColours) {
    this.colours = colours
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => {
        this.draw(target)
      },
    }
    this.views = [{ zOrder: () => 'bottom', renderer: () => renderer }]
  }

  attached(param: SeriesAttachedParameter): void {
    this.chart = param.chart
    this.series = param.series
    this.requestUpdate = param.requestUpdate
  }

  detached(): void {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views
  }

  setZones(zones: readonly Zone[], times: readonly number[]): void {
    this.zones = zones
    this.times = times
    this.requestUpdate?.()
  }

  private draw(target: DrawTarget): void {
    const chart = this.chart
    const series = this.series
    if (chart === null || series === null || this.zones.length === 0) return
    const scale = chart.timeScale()
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const rects = zoneRects(
        this.zones,
        this.times,
        (logical) => edgeX((index) => scale.logicalToCoordinate(index as Logical), logical),
        (price) => series.priceToCoordinate(price),
        mediaSize.height,
      )
      // the trends first, so the rectangles stay on top of their shading
      for (const r of rects) {
        if (r.kind === 'consolidation') continue
        context.globalAlpha = 0.1
        context.fillStyle = this.colours[r.kind]
        context.fillRect(r.x, r.y, r.width, r.height)
      }
      context.font = '600 11px system-ui, sans-serif'
      context.textBaseline = 'bottom'
      for (const r of rects) {
        if (r.kind !== 'consolidation') continue
        const colour = r.selected ? this.colours.selected : this.colours.consolidation
        context.globalAlpha = r.selected ? 0.28 : 0.16
        context.fillStyle = colour
        context.fillRect(r.x, r.y, r.width, r.height)
        context.globalAlpha = 1
        context.lineWidth = r.selected ? 3 : 2
        context.strokeStyle = colour
        context.strokeRect(r.x, r.y, r.width, r.height)
        if (r.label !== undefined) {
          // above the rectangle, or inside its top when there is no room above
          // a narrow rectangle gets the short part: "8 candles"
          const text =
            context.measureText(r.label).width <= Math.max(r.width, 90)
              ? r.label
              : (r.label.split(' · ')[1] ?? '')
          const y = r.y - 3 >= 12 ? r.y - 3 : r.y + 14
          context.fillText(text, r.x + 2, y)
        }
      }
      context.globalAlpha = 1
    })
  }
}
