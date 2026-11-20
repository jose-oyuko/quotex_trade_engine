// Boxes and shaded stretches drawn under the candles (decision D-85): a consolidation is a box from
// its range's low to its high, a trend a band over the whole height. A "series primitive" is the
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
  /** The price range of a box; null for a band over the whole height. */
  top: number | null
  bottom: number | null
  kind: ZoneKind
  selected: boolean
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
  kind: ZoneKind
  selected: boolean
}

export interface ZoneColours {
  consolidation: string
  up: string
  down: string
  selected: string
}

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

/** Where each zone is drawn, in pixels; zones off the chart or without width are left out. */
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
      top = Math.min(high, low)
      bottom = Math.max(high, low)
    }
    rects.push({
      x: left,
      y: top,
      width: right - left,
      height: Math.max(bottom - top, 1),
      kind: zone.kind,
      selected: zone.selected,
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
        (logical) => scale.logicalToCoordinate(logical as Logical),
        (price) => series.priceToCoordinate(price),
        mediaSize.height,
      )
      for (const r of rects) {
        const colour = this.colours[r.kind]
        context.globalAlpha = r.kind === 'consolidation' ? (r.selected ? 0.3 : 0.16) : 0.08
        context.fillStyle = colour
        context.fillRect(r.x, r.y, r.width, r.height)
        if (r.kind === 'consolidation' || r.selected) {
          context.globalAlpha = 1
          context.lineWidth = r.selected ? 3 : 1
          context.strokeStyle = r.selected ? this.colours.selected : colour
          context.strokeRect(r.x, r.y, r.width, r.height)
        }
      }
      context.globalAlpha = 1
    })
  }
}
