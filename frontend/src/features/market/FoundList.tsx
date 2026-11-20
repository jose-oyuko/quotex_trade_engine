// The consolidations a scan found, in time order: when, how many candles, the range, the breakout
// and the trend after it. "Show" moves the chart there and marks it.
import { useState } from 'react'
import type { Consolidation, Scan } from '../../api/types'
import { Button } from '../../components/Button'
import { candlesText, trendAfter } from './marketSchema'

const PAGE = 100

const when = (iso: string) => iso.slice(0, 16).replace('T', ' ')

function breakoutText(c: Consolidation): string {
  if (c.breakout) return c.breakout.direction === 'up' ? '↑ up' : '↓ down'
  return c.ended === 'gap' ? 'none (prices missing)' : 'none yet'
}

export function FoundList({
  scan,
  selected,
  onShow,
}: {
  scan: Scan
  selected: number | null
  onShow: (index: number) => void
}) {
  const [shown, setShown] = useState(PAGE)
  const trends = trendAfter(scan)
  if (scan.consolidations.length === 0) {
    return <p className="state-empty">No consolidation in this period with this definition.</p>
  }
  return (
    <>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Consolidations found</caption>
          <thead>
            <tr>
              <th scope="col">Starts (UTC)</th>
              <th scope="col">Candles</th>
              <th scope="col">Range</th>
              <th scope="col">Breakout</th>
              <th scope="col">Trend after</th>
              <th scope="col">
                <span className="sr-only">Show on the chart</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {scan.consolidations.slice(0, shown).map((c, i) => {
              const trend = trends.get(i)
              return (
                <tr key={c.first} className={i === selected ? 'tab-active' : undefined}>
                  <th scope="row">{when(c.first)}</th>
                  <td>{c.candles}</td>
                  <td>
                    {c.low} – {c.high}
                  </td>
                  <td>{breakoutText(c)}</td>
                  <td>
                    {trend
                      ? `${candlesText(trend.candles, scan.length)}${trend.ended === 'consolidation' ? '' : ', then prices end'}`
                      : '–'}
                  </td>
                  <td>
                    <Button
                      aria-pressed={i === selected}
                      onClick={() => {
                        onShow(i)
                      }}
                    >
                      Show
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {scan.consolidations.length > shown && (
        <Button
          onClick={() => {
            setShown((n) => n + PAGE)
          }}
        >
          Show {Math.min(PAGE, scan.consolidations.length - shown)} more
        </Button>
      )}
    </>
  )
}
