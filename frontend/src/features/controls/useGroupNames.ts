import { useMemo } from 'react'
import { useGroups, useSessions } from '../../api/queries'

/**
 * Group id -> title, for tables that only have the id. A trading session's hidden group is named
 * after the session. Falls back to "Group 3" while loading.
 */
export function useGroupNames(): (id: number) => string {
  const { data } = useGroups()
  const sessions = useSessions().data
  const names = useMemo(() => {
    const all = new Map((data?.items ?? []).map((g) => [g.id, g.title]))
    for (const s of sessions?.items ?? []) all.set(s.group_id, `Session: ${s.name}`)
    return all
  }, [data, sessions])
  return (id) => names.get(id) ?? `Group ${String(id)}`
}
