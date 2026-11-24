import { describe, expect, it } from 'vitest'
import { PAD_PX, edgeX, logicalOf, zoneRects, type Zone } from './zones'

// candles at 0, 60, 120 ... 540 seconds; one candle is 10 px wide, a price unit 2 px tall
const times = Array.from({ length: 10 }, (_, i) => i * 60)
const x = (logical: number) => 100 + logical * 10
const y = (price: number) => 500 - price * 2

const zone = (overrides: Partial<Zone>): Zone => ({
  from: 120,
  to: 420,
  top: 110,
  bottom: 100,
  kind: 'consolidation',
  selected: false,
  ...overrides,
})

describe('where zones are drawn', () => {
  it('finds a moment among the candles', () => {
    expect(logicalOf(times, 0)).toBe(-0.5)
    expect(logicalOf(times, 120)).toBe(1.5)
    expect(logicalOf(times, 130)).toBe(2.5) // inside candle 2: drawn from its far edge
    expect(logicalOf(times, 600)).toBe(9.5) // the end of the last candle
  })

  it('draws a consolidation as a box over its range and a trend over the whole height', () => {
    const [box, band] = zoneRects(
      [zone({}), zone({ kind: 'up', top: null, bottom: null, from: 420, to: 600 })],
      times,
      x,
      y,
      400,
    )
    expect(box).toEqual({
      x: 115,
      y: 280 - PAD_PX,
      width: 50,
      height: 20 + 2 * PAD_PX,
      kind: 'consolidation',
      selected: false,
    })
    expect(band).toMatchObject({ x: 165, y: 0, width: 30, height: 400, kind: 'up' })
  })

  it('finds the edges between candles with whole candle positions only, like the chart', () => {
    // the chart library converts whole positions only and gives 0 for anything in between: the
    // first version asked it for 1.5, 6.5 ... and every rectangle came out 0 pixels wide
    const chartX = (index: number) => (Number.isInteger(index) ? 100 + index * 10 : 0)
    expect(edgeX(chartX, 1.5)).toBe(115)
    expect(edgeX(chartX, -0.5)).toBe(95)
    const [box] = zoneRects(
      [zone({ label: 'Consolidation · 5 candles' })],
      times,
      (logical) => edgeX(chartX, logical),
      y,
      400,
    )
    expect(box).toMatchObject({ x: 115, width: 50, label: 'Consolidation · 5 candles' })
    expect(edgeX(() => null, 1.5)).toBeNull()
  })

  it('leaves out zones off the chart or without width', () => {
    const offChart = (logical: number) => (logical > 5 ? null : x(logical))
    expect(zoneRects([zone({})], times, offChart, y, 400)).toEqual([])
    expect(zoneRects([zone({ to: 120 })], times, x, y, 400)).toEqual([])
  })
})
