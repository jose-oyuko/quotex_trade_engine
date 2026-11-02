import { useState } from 'react'
import { useGroups, useSignals } from '../../api/queries'
import type { SignalStatus } from '../../api/types'
import { DataState } from '../../components/DataState'
import { Pagination } from '../../components/Pagination'
import { SignalsTable } from './SignalsTable'

const STATUSES: SignalStatus[] = ['parsed', 'ignored', 'not_parsed']

export default function SignalsPage() {
  const [groupId, setGroupId] = useState<number | undefined>(undefined)
  const [status, setStatus] = useState<SignalStatus | undefined>(undefined)
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const groups = useGroups()
  const signals = useSignals({ limit, offset, group_id: groupId, status })

  return (
    <section aria-labelledby="signals-heading">
      <h1 id="signals-heading">Signal inbox</h1>
      <p className="lead">
        Every message the groups sent, what became of it, and why. Messages that were not signals
        are kept too, so you can check the parser.
      </p>
      <div className="filters">
        <label>
          Group{' '}
          <select
            value={groupId ?? ''}
            onChange={(event) => {
              setGroupId(event.target.value === '' ? undefined : Number(event.target.value))
              setOffset(0)
            }}
          >
            <option value="">All groups</option>
            {(groups.data?.items ?? []).map((group) => (
              <option key={group.id} value={group.id}>
                {group.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Result{' '}
          <select
            value={status ?? ''}
            onChange={(event) => {
              setStatus(
                event.target.value === '' ? undefined : (event.target.value as SignalStatus),
              )
              setOffset(0)
            }}
          >
            <option value="">All</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value.replace('_', ' ')}
              </option>
            ))}
          </select>
        </label>
      </div>
      <DataState
        query={signals}
        isEmpty={(page) => page.total === 0}
        empty="No messages yet. They appear here as soon as a group posts."
      >
        {(page) => (
          <>
            <SignalsTable signals={page.items} />
            <Pagination
              offset={offset}
              limit={limit}
              total={page.total}
              onChange={setOffset}
              onLimitChange={(next) => {
                setLimit(next)
                setOffset(0)
              }}
            />
          </>
        )}
      </DataState>
    </section>
  )
}
