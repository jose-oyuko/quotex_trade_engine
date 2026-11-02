import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { invalidateGroups, useGroup } from '../../api/queries'
import { DataState } from '../../components/DataState'
import { GroupForm } from './GroupForm'
import { EMPTY_GROUP, fromGroup, toCreate, toUpdate, type GroupFormValues } from './groupSchema'

function useSaveGroup(id: number | null) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const save = useMutation({
    mutationFn: (values: GroupFormValues) =>
      id === null ? api.groups.create(toCreate(values)) : api.groups.update(id, toUpdate(values)),
    onSuccess: async () => {
      await invalidateGroups(client)
      void navigate('/groups')
    },
  })
  return async (values: GroupFormValues) => {
    await save.mutateAsync(values) // a failure is thrown to the form, which shows it on its fields
  }
}

function NewGroup() {
  const navigate = useNavigate()
  const submit = useSaveGroup(null)
  return (
    <GroupForm
      mode="create"
      initial={EMPTY_GROUP}
      onSubmit={submit}
      onCancel={() => void navigate('/groups')}
    />
  )
}

function EditGroup({ id }: { id: number }) {
  const navigate = useNavigate()
  const group = useGroup(id)
  const submit = useSaveGroup(id)
  return (
    <DataState query={group}>
      {(data) => (
        <GroupForm
          mode="edit"
          initial={fromGroup(data)}
          onSubmit={submit}
          onCancel={() => void navigate('/groups')}
        />
      )}
    </DataState>
  )
}

export default function GroupFormPage() {
  const { id } = useParams()
  const groupId = id === undefined ? null : Number(id)
  const invalid = groupId !== null && !Number.isInteger(groupId)
  return (
    <section aria-labelledby="group-form-heading">
      <h1 id="group-form-heading">{groupId === null ? 'Add a group' : 'Edit group'}</h1>
      {groupId !== null && (
        <p className="lead">
          Chains that are already running keep the settings they started with; the new settings
          apply to chains that start from now on.
        </p>
      )}
      {invalid ? (
        <p role="alert" className="form-error">
          That is not a group.
        </p>
      ) : groupId === null ? (
        <NewGroup />
      ) : (
        <EditGroup id={groupId} />
      )}
    </section>
  )
}
