import { useId } from 'react'

export interface Point {
  label: string
  value: number
}

const WIDTH = 640
const PAD_X = 12
const PAD_Y = 14
const LABEL_SPACE = 22

/**
 * A line chart as plain SVG (decision D-48), for the running total of profit. The zero line is
 * always drawn, so "above water" and "below water" are plain to see. A table of the same numbers
 * accompanies it on the page; the chart carries a one-sentence description for screen readers.
 */
export function LineChart({
  points,
  label,
  height = 240,
  format = String,
}: {
  points: Point[]
  label: string
  height?: number
  format?: (value: number) => string
}) {
  const id = useId()
  if (points.length === 0) return <p className="state-empty">Nothing to chart yet.</p>

  const values = points.map((p) => p.value)
  const top = Math.max(0, ...values)
  const bottom = Math.min(0, ...values)
  const span = top - bottom || 1
  const plotHeight = height - PAD_Y * 2 - LABEL_SPACE
  const y = (value: number) => PAD_Y + ((top - value) / span) * plotHeight
  const x = (index: number) =>
    points.length === 1 ? WIDTH / 2 : PAD_X + (index / (points.length - 1)) * (WIDTH - PAD_X * 2)

  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
    .join(' ')
  const first = points[0]
  const last = points[points.length - 1]
  const summary = `${label}. From ${first?.label ?? ''}: ${format(first?.value ?? 0)}; to ${last?.label ?? ''}: ${format(last?.value ?? 0)}. Lowest ${format(bottom)}, highest ${format(top)}.`

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${String(WIDTH)} ${String(height)}`}
      role="img"
      aria-labelledby={`${id}-t`}
      aria-describedby={`${id}-d`}
    >
      <title id={`${id}-t`}>{label}</title>
      <desc id={`${id}-d`}>{summary}</desc>
      <line className="chart-axis" x1={PAD_X} x2={WIDTH - PAD_X} y1={y(0)} y2={y(0)} />
      <path className="chart-line" d={path} fill="none" />
      {points.length <= 45 &&
        points.map((p, i) => (
          <circle
            key={`${p.label}-${String(i)}`}
            className="chart-dot"
            cx={x(i)}
            cy={y(p.value)}
            r={3}
          >
            <title>{`${p.label}: ${format(p.value)}`}</title>
          </circle>
        ))}
      <text className="chart-label" x={PAD_X} y={height - 6} textAnchor="start">
        {first?.label}
      </text>
      <text className="chart-label" x={WIDTH - PAD_X} y={height - 6} textAnchor="end">
        {last?.label}
      </text>
      <text className="chart-label" x={WIDTH - PAD_X} y={y(0) - 4} textAnchor="end">
        0
      </text>
    </svg>
  )
}
