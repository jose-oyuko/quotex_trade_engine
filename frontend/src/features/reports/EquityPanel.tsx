import type { ReportFilters } from '../../api/client'
import { useReportEquity } from '../../api/queries'
import { LineChart } from '../../components/charts/LineChart'
import { DataState } from '../../components/DataState'
import { Money } from '../../components/Money'

/** The running total of profit, day by day: the shape of the result over time. */
export function EquityPanel({ filters }: { filters: ReportFilters }) {
  const query = useReportEquity(filters)
  return (
    <section aria-labelledby="equity-heading">
      <h2 id="equity-heading">Profit over time</h2>
      <DataState
        query={query}
        isEmpty={(data) => data.points.length === 0}
        empty="No finished trades in this range."
      >
        {(data) => (
          <>
            <LineChart
              label="Running total of profit, by day"
              format={(value) => value.toFixed(2)}
              points={data.points.map((p) => ({ label: p.day, value: Number(p.cumulative) }))}
            />
            <details>
              <summary>Show the numbers</summary>
              <div className="table-wrap">
                <table>
                  <caption className="sr-only">Profit by day</caption>
                  <thead>
                    <tr>
                      <th scope="col">Day</th>
                      <th scope="col">Trades</th>
                      <th scope="col">Result</th>
                      <th scope="col">Running total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.points].reverse().map((p) => (
                      <tr key={p.day}>
                        <th scope="row">{p.day}</th>
                        <td>{p.trades}</td>
                        <td>
                          <Money value={p.profit} signed />
                        </td>
                        <td>
                          <Money value={p.cumulative} signed />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </DataState>
    </section>
  )
}
