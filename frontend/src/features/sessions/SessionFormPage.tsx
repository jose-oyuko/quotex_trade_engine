import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { invalidateSessions, useSession } from '../../api/queries'
import { DataState } from '../../components/DataState'
import { SessionForm } from './SessionForm'
import { EMPTY_SESSION, fromSession, toInput, type SessionFormValues } from './sessionSchema'

function useSaveSession(id: number | null) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const save = useMutation({
    mutationFn: (values: SessionFormValues) =>
      id === null ? api.sessions.create(toInput(values)) : api.sessions.update(id, toInput(values)),
    onSuccess: async () => {
      await invalidateSessions(client)
      void navigate('/sessions')
    },
  })
  return async (values: SessionFormValues) => {
    await save.mutateAsync(values) // a failure is thrown to the form, which shows it on its fields
  }
}

function NewSession() {
  const navigate = useNavigate()
  const submit = useSaveSession(null)
  return (
    <SessionForm
      mode="create"
      initial={EMPTY_SESSION}
      onSubmit={submit}
      onCancel={() => void navigate('/sessions')}
    />
  )
}

function EditSession({ id }: { id: number }) {
  const navigate = useNavigate()
  const session = useSession(id)
  const submit = useSaveSession(id)
  return (
    <DataState query={session}>
      {(data) => (
        <SessionForm
          mode="edit"
          initial={fromSession(data)}
          onSubmit={submit}
          onCancel={() => void navigate('/sessions')}
        />
      )}
    </DataState>
  )
}

export default function SessionFormPage() {
  const { id } = useParams()
  const sessionId = id === undefined ? null : Number(id)
  const invalid = sessionId !== null && !Number.isInteger(sessionId)
  return (
    <section aria-labelledby="session-form-heading">
      <h1 id="session-form-heading">{sessionId === null ? 'Add a session' : 'Edit session'}</h1>
      <p className="lead">
        A session trades by the clock, with no Telegram signal: while its window is open it opens
        pairs (a CALL and a PUT together) on one asset. Only one session runs at a time, so two
        enabled sessions cannot have overlapping windows.
      </p>
      {invalid ? (
        <p role="alert" className="form-error">
          That is not a session.
        </p>
      ) : sessionId === null ? (
        <NewSession />
      ) : (
        <EditSession id={sessionId} />
      )}
    </section>
  )
}
