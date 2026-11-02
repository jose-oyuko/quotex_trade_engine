import { useMemo } from 'react'
import { useGroups } from '../../api/queries'

/** Group id -> title, for tables that only have the id. Falls back to "Group 3" while loading. */
export function useGroupNames(): (id: number) => string {
  const { data } = useGroups()
  const names = useMemo(() => new Map((data?.items ?? []).map((g) => [g.id, g.title])), [data])
  return (id) => names.get(id) ?? `Group ${String(id)}`
}
