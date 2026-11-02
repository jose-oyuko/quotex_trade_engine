import { useId } from 'react'

export interface Bar {
  label: string
  value: number
  /** Extra words for the tooltip and the screen-reader summary. */
  note?: string
}

const WIDTH = 640
const LABEL_SPACE = 28
const PAD = 8

/**
 * A bar chart drawn as plain SVG (decision D-48: no chart library). `signed` colours bars by
 * profit or loss and draws them from a zero line; otherwise bars start at the bottom. Every chart is
 * paired with a table of the same numbers on the page, so nothing is only in the picture; the chart
 * itself carries a one-sentence description for screen readers.
 */
export function BarChart({
  bars,
  label,
  signed = false,
  height = 220,
  format = String,
}: {
  bars: Bar[]
  label: string
  signed?: boolean
  height?: number
  format?: (value: number) => string
}) {
  const id = useId()
  if (bars.length === 0) return <p className="state-empty">Nothing to chart yet.</p>

  const plotHeight = height - LABEL_SPACE - PAD
  const top = Math.max(0, ...bars.map((b) => b.value))
  const bottom = signed ? Math.min(0, ...bars.map((b) => b.value)) : 0
  const span = top - bottom || 1
  const zeroY = PAD + (top / span) * plotHeight
  const slot = (WIDTH - PAD * 2) / bars.length
  const barWidth = Math.max(2, slot * 0.7)
  const every = Math.ceil(bars.length / 12) // never crowd the labels

  const best = bars.reduce((a, b) => (b.value > a.value ? b : a))
  const worst = bars.reduce((a, b) => (b.value < a.value ? b : a))
  const summary = `${label}. Highest: ${best.label}, ${format(best.value)}. Lowest: ${worst.label}, ${format(worst.value)}.`

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
      <line className="chart-axis" x1={PAD} x2={WIDTH - PAD} y1={zeroY} y2={zeroY} />
      {bars.map((bar, index) => {
        const x = PAD + index * slot + (slot - barWidth) / 2
        const h = Math.abs(bar.value / span) * plotHeight
        const y = bar.value >= 0 ? zeroY - h : zeroY
        const tone = !signed
          ? 'chart-bar'
          : bar.value >= 0
            ? 'chart-bar chart-good'
            : 'chart-bar chart-bad'
        return (
          <g key={`${bar.label}-${String(index)}`}>
            <rect
              className={tone}
              x={x}
              y={y}
              width={barWidth}
              height={Math.max(h, bar.value === 0 ? 0 : 1)}
            >
              <title>{`${bar.label}: ${format(bar.value)}${bar.note ? ` (${bar.note})` : ''}`}</title>
            </rect>
            {index % every === 0 && (
              <text className="chart-label" x={x + barWidth / 2} y={height - 8} textAnchor="middle">
                {bar.label}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
