import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BarChart } from './BarChart'
import { LineChart } from './LineChart'

const num = (element: Element, attribute: string) => Number(element.getAttribute(attribute))

describe('BarChart', () => {
  const bars = [
    { label: 'Mon', value: 4, note: '3 trades' },
    { label: 'Tue', value: -2 },
    { label: 'Wed', value: 0 },
  ]

  it('is an image with a name and a description a screen reader can read', () => {
    render(<BarChart bars={bars} label="Profit by weekday" signed format={(v) => v.toFixed(2)} />)
    const chart = screen.getByRole('img', { name: 'Profit by weekday' })
    expect(chart).toHaveAccessibleDescription(
      'Profit by weekday. Highest: Mon, 4.00. Lowest: Tue, -2.00.',
    )
  })

  it('draws bars in proportion to their values, up for profit and down for loss', () => {
    const { container } = render(<BarChart bars={bars} label="x" signed />)
    const [mon, tue, wed] = [...container.querySelectorAll('rect')]
    const axis = container.querySelector('line.chart-axis')
    if (!mon || !tue || !wed || !axis) throw new Error('chart parts missing')
    const zeroY = num(axis, 'y1')
    expect(num(mon, 'y') + num(mon, 'height')).toBeCloseTo(zeroY) // sits on the zero line, above it
    expect(num(tue, 'y')).toBeCloseTo(zeroY) // hangs from the zero line, below it
    expect(num(mon, 'height') / num(tue, 'height')).toBeCloseTo(2) // 4 is twice 2
    expect(num(wed, 'height')).toBe(0)
  })

  it('colours profit and loss differently, and draws them in one colour when not signed', () => {
    const { container, rerender } = render(<BarChart bars={bars} label="x" signed />)
    const rects = () => [...container.querySelectorAll('rect')]
    expect(rects().map((r) => r.getAttribute('class'))).toEqual([
      'chart-bar chart-good',
      'chart-bar chart-bad',
      'chart-bar chart-good',
    ])
    rerender(<BarChart bars={bars.map((b) => ({ ...b, value: Math.abs(b.value) }))} label="x" />)
    expect(new Set(rects().map((r) => r.getAttribute('class')))).toEqual(new Set(['chart-bar']))
  })

  it('starts unsigned bars at the bottom', () => {
    const { container } = render(<BarChart bars={[{ label: 'a', value: 5 }]} label="x" />)
    const rect = container.querySelector('rect')
    const axis = container.querySelector('line.chart-axis')
    if (!rect || !axis) throw new Error('chart parts missing')
    expect(num(rect, 'y') + num(rect, 'height')).toBeCloseTo(num(axis, 'y1'))
  })

  it('gives every bar a tooltip with its value and note', () => {
    render(<BarChart bars={bars} label="x" signed format={(v) => v.toFixed(1)} />)
    expect(screen.getByText('Mon: 4.0 (3 trades)')).toBeInTheDocument()
    expect(screen.getByText('Tue: -2.0')).toBeInTheDocument()
  })

  it('does not crowd the axis: with 24 bars only some are labelled', () => {
    const many = Array.from({ length: 24 }, (_, h) => ({
      label: `${String(h).padStart(2, '0')}:00`,
      value: h,
    }))
    const { container } = render(<BarChart bars={many} label="By hour" />)
    expect(container.querySelectorAll('rect')).toHaveLength(24)
    expect(container.querySelectorAll('text').length).toBeLessThan(24)
    expect(container.querySelectorAll('text').length).toBeGreaterThan(5)
  })

  it('copes with all-zero data without dividing by zero', () => {
    const { container } = render(<BarChart bars={[{ label: 'a', value: 0 }]} label="x" signed />)
    const rect = container.querySelector('rect')
    expect(Number.isFinite(num(rect as Element, 'y'))).toBe(true)
  })

  it('says so when there is nothing to chart', () => {
    render(<BarChart bars={[]} label="x" />)
    expect(screen.getByText('Nothing to chart yet.')).toBeInTheDocument()
  })
})

describe('LineChart', () => {
  const points = [
    { label: '2026-11-02', value: 1.4 },
    { label: '2026-11-03', value: -7.6 },
    { label: '2026-11-04', value: -2.5 },
  ]

  it('is an image whose description gives the start, the end and the extremes', () => {
    render(<LineChart points={points} label="Running total" format={(v) => v.toFixed(2)} />)
    expect(screen.getByRole('img', { name: 'Running total' })).toHaveAccessibleDescription(
      'Running total. From 2026-11-02: 1.40; to 2026-11-04: -2.50. Lowest -7.60, highest 1.40.',
    )
  })

  it('draws one line through every point, with the zero line between the high and the low', () => {
    const { container } = render(<LineChart points={points} label="x" />)
    const path = container.querySelector('path.chart-line')?.getAttribute('d') ?? ''
    expect(path.match(/[ML]/g)).toHaveLength(3)
    const ys = [...path.matchAll(/,(-?[\d.]+)/g)].map((m) => Number(m[1]))
    const axis = container.querySelector('line.chart-axis')
    const zeroY = num(axis as Element, 'y1')
    expect(ys[0]).toBeLessThan(zeroY) // +1.40 is above the zero line (smaller y is higher)
    expect(ys[1]).toBeGreaterThan(zeroY) // -7.60 below it
    expect(ys[1]).toBeGreaterThan(ys[2] ?? 0) // the lowest point is the lowest on screen
  })

  it('keeps the zero line in view even when every value is below it', () => {
    const { container } = render(
      <LineChart
        points={[
          { label: 'a', value: -3 },
          { label: 'b', value: -5 },
        ]}
        label="x"
      />,
    )
    const zeroY = num(container.querySelector('line.chart-axis') as Element, 'y1')
    const ys = [
      ...(container.querySelector('path.chart-line')?.getAttribute('d') ?? '').matchAll(
        /,(-?[\d.]+)/g,
      ),
    ].map((m) => Number(m[1]))
    expect(ys.every((y) => y > zeroY)).toBe(true) // both points are below the zero line
    expect(zeroY).toBeGreaterThanOrEqual(0) // the zero line is on the chart, not above it
    expect(zeroY).toBeLessThan(40) // at the top of the plot
  })

  it('marks each point with a tooltip when there are few, and only the line when there are many', () => {
    const { container, rerender } = render(<LineChart points={points} label="x" />)
    expect(container.querySelectorAll('circle')).toHaveLength(3)
    expect(screen.getByText('2026-11-03: -7.6')).toBeInTheDocument()
    const many = Array.from({ length: 100 }, (_, i) => ({ label: `d${String(i)}`, value: i }))
    rerender(<LineChart points={many} label="x" />)
    expect(container.querySelectorAll('circle')).toHaveLength(0)
    expect(container.querySelector('path.chart-line')).not.toBeNull()
  })

  it('draws a single point in the middle, and flat data without dividing by zero', () => {
    const { container, rerender } = render(
      <LineChart points={[{ label: 'a', value: 3 }]} label="x" />,
    )
    expect(num(container.querySelector('circle') as Element, 'cx')).toBe(320)
    rerender(
      <LineChart
        points={[
          { label: 'a', value: 0 },
          { label: 'b', value: 0 },
        ]}
        label="x"
      />,
    )
    expect(container.querySelector('path.chart-line')?.getAttribute('d')).not.toContain('NaN')
  })

  it('says so when there is nothing to chart', () => {
    render(<LineChart points={[]} label="x" />)
    expect(screen.getByText('Nothing to chart yet.')).toBeInTheDocument()
  })
})
