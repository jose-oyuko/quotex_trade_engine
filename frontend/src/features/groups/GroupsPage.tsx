import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { invalidateGroups, useGroups } from '../../api/queries'
import type { Group } from '../../api/types'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { DataState } from '../../components/DataState'
import { errorMessage } from '../../lib/errors'
import { Money } from '../../components/Money'
import { titleCase } from '../../lib/format'
import { fromGroup, toUpdate } from './groupSchema'

function GroupRow({ group, onDelete }: { group: Group; onDelete: (group: Group) => void }) {
  const client = useQueryClient()
  const change = useMutation({
    mutationFn: async (action: 'toggle' | 'pause' | 'resume') => {
      if (action === 'pause') return api.groups.pause(group.id)
      if (action === 'resume') return api.groups.resume(group.id)
      const values = fromGroup(group)
      return api.groups.update(group.id, toUpdate({ ...values, enabled: !group.enabled }))
    },
    onSuccess: () => invalidateGroups(client),
  })
  const settings = group.settings
  return (
    <>
      <tr>
        <td>
          <strong>{group.title}</strong>
          <br />
          <small>chat {group.telegram_chat_id}</small>
        </td>
        <td>{settings ? titleCase(settings.strategy) : '—'}</td>
        <td>{settings ? <Money value={settings.base_stake} /> : '—'}</td>
        <td>
          {settings && settings.max_steps > 0
            ? `${String(settings.max_steps)} × (${settings.multipliers.join(', ')})`
            : 'none'}
        </td>
        <td>{settings ? `${String(settings.min_payout_pct)}%` : '—'}</td>
        <td>
          <Badge tone={group.enabled ? 'good' : 'muted'}>
            {group.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
          {group.paused && <Badge tone="warn">Paused</Badge>}
        </td>
        <td>{group.active_chains}</td>
        <td className="actions">
          <Link
            className="btn btn-default"
            to={`/groups/${String(group.id)}/edit`}
            aria-label={`Edit ${group.title}`}
          >
            Edit
          </Link>
          <Button
            onClick={() => {
              change.mutate('toggle')
            }}
            disabled={change.isPending}
            aria-label={`${group.enabled ? 'Disable' : 'Enable'} ${group.title}`}
          >
            {group.enabled ? 'Disable' : 'Enable'}
          </Button>
          <Button
            onClick={() => {
              change.mutate(group.paused ? 'resume' : 'pause')
            }}
            disabled={change.isPending}
            aria-label={`${group.paused ? 'Resume' : 'Pause'} ${group.title}`}
          >
            {group.paused ? 'Resume' : 'Pause'}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              onDelete(group)
            }}
            aria-label={`Delete ${group.title}`}
          >
            Delete…
          </Button>
        </td>
      </tr>
      {change.isError && (
        <tr>
          <td colSpan={8}>
            <p role="alert" className="form-error">
              {group.title}: {errorMessage(change.error)}
            </p>
          </td>
        </tr>
      )}
    </>
  )
}

export default function GroupsPage() {
  const groups = useGroups()
  const client = useQueryClient()
  const [deleting, setDeleting] = useState<Group | null>(null)
  const remove = useMutation({
    mutationFn: (group: Group) => api.groups.remove(group.id),
    onSuccess: async () => {
      setDeleting(null)
      await invalidateGroups(client)
    },
  })

  return (
    <section aria-labelledby="groups-heading">
      <div className="page-head">
        <h1 id="groups-heading">Groups</h1>
        <Link className="btn btn-primary" to="/groups/new">
          Add a group
        </Link>
      </div>
      <p className="lead">
        Each group has its own strategy. Pausing a group ignores its new signals while its running
        chains finish. Disabling stops listening to it altogether.
      </p>
      <DataState
        query={groups}
        isEmpty={(page) => page.total === 0}
        empty="No groups yet. Add one to start listening to its signals."
      >
        {(page) => (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Telegram groups and their strategies</caption>
              <thead>
                <tr>
                  <th scope="col">Group</th>
                  <th scope="col">Strategy</th>
                  <th scope="col">Base stake</th>
                  <th scope="col">Steps × multipliers</th>
                  <th scope="col">Min payout</th>
                  <th scope="col">Status</th>
                  <th scope="col">Chains running</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((group) => (
                  <GroupRow key={group.id} group={group} onDelete={setDeleting} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </DataState>

      {deleting !== null && (
        <ConfirmDialog
          title="Delete this group?"
          confirmLabel="Delete group"
          danger
          busy={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => {
            remove.mutate(deleting)
          }}
          onCancel={() => {
            setDeleting(null)
            remove.reset()
          }}
        >
          <p>
            Delete <strong>{deleting.title}</strong> and its settings. This only works for a group
            with no history; otherwise disable it instead.
          </p>
        </ConfirmDialog>
      )}
    </section>
  )
}
