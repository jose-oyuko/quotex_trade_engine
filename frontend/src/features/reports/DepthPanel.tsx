import type { ReportFilters } from '../../api/client'
import { useReportDepth } from '../../api/queries'
import { BarChart } from '../../components/charts/BarChart'
import { DataState } from '../../components/DataState'
import { Money } from '../../components/Money'
import { formatPercent } from '../../lib/format'

/**
 * How deep chains go. Trade 1 is the original signal's trade; each further trade is a follow-up
 * after a loss. The deeper a chain goes, the more it has staked, so the table shows what each
 * step cost and how the chains that stopped there ended.
 */
export function DepthPanel({ filters }: { filters: ReportFilters }) {
  const query = useReportDepth(filters)
  return (
    <section aria-labelledby="depth-heading">
      <h2 id="depth-heading">How deep chains go</h2>
      <DataState
        query={query}
        isEmpty={(data) => data.chains === 0}
        empty="No finished chains in this range."
      >
        {(data) => (
          <>
            <p className="lead">
              {data.chains} chains: {data.completed} ended on a win, {data.exhausted} lost every
              step
              {data.other > 0 ? `, ${String(data.other)} ended another way` : ''}. Average result
              per chain: <Money value={data.avg_chain_profit} signed />.
            </p>
            <BarChart
              label="Share of chains that reached each trade"
              format={(value) => `${(value * 100).toFixed(1)}%`}
              bars={data.steps.map((row) => ({
                label: `Trade ${String(row.step)}`,
                value: row.share_of_chains,
                note: `${String(row.chains_reaching)} chains`,
              }))}
            />
            <div className="table-wrap">
              <table>
                <caption className="sr-only">What each step of a chain cost</caption>
                <thead>
                  <tr>
                    <th scope="col">Trade in the chain</th>
                    <th scope="col">Chains that got here</th>
                    <th scope="col">Share of chains</th>
                    <th scope="col">Trades won / lost</th>
                    <th scope="col">Staked here</th>
                    <th scope="col">Result of these trades</th>
                    <th scope="col">Chains that ended here</th>
                    <th scope="col">…ended on a win</th>
                    <th scope="col">Whole-chain result of those</th>
                  </tr>
                </thead>
                <tbody>
                  {data.steps.map((row) => (
                    <tr key={row.step}>
                      <th scope="row">{row.step}</th>
                      <td>{row.chains_reaching}</td>
                      <td>{formatPercent(row.share_of_chains)}</td>
                      <td>
                        {row.wins} / {row.losses}
                      </td>
                      <td>
                        <Money value={row.staked} />
                      </td>
                      <td>
                        <Money value={row.profit} signed />
                      </td>
                      <td>{row.chains_ending_here}</td>
                      <td>{row.chains_won_here}</td>
                      <td>
                        <Money value={row.chain_profit_ending_here} signed />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </DataState>
    </section>
  )
}
