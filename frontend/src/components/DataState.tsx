import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { errorMessage } from '../lib/errors'
import { Button } from './Button'

/**
 * The three states every piece of server data has besides "here it is": loading, failed (with a
 * retry) and empty. `isEmpty` decides what empty means for the data at hand.
 */
export function DataState<T>({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: UseQueryResult<T>
  isEmpty?: (data: T) => boolean
  empty?: ReactNode
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <p role="status">Loading…</p>
  if (query.isError) {
    return (
      <div role="alert" className="state-error">
        <p>{errorMessage(query.error)}</p>
        <Button
          onClick={() => {
            void query.refetch()
          }}
        >
          Try again
        </Button>
      </div>
    )
  }
  if (isEmpty?.(query.data) === true) {
    return <p className="state-empty">{empty ?? 'Nothing here yet.'}</p>
  }
  return <>{children(query.data)}</>
}
