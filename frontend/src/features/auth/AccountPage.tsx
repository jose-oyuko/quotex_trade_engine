import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { keys } from '../../api/queries'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'
import { passwordProblem } from '../../lib/password'
import { TextField } from './TextField'
import { useLogout } from './useLogout'

export default function AccountPage() {
  const auth = useQuery({
    queryKey: keys.auth,
    queryFn: ({ signal }) => api.auth.state(signal),
    staleTime: Infinity,
  })
  const logout = useLogout()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const change = useMutation({
    mutationFn: () => api.auth.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setRepeat('')
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = passwordProblem(next, repeat)
    setProblem(found)
    if (found === null) change.mutate()
  }

  const shown = problem ?? (change.isError ? errorMessage(change.error) : null)
  return (
    <section aria-labelledby="account-heading">
      <h1 id="account-heading">Account</h1>
      <p className="lead">
        Logged in as <strong>{auth.data?.user?.username ?? '…'}</strong>.
      </p>
      <form onSubmit={submit}>
        <fieldset>
          <legend>Change the password</legend>
          <TextField
            label="Current password"
            type="password"
            value={current}
            onChange={setCurrent}
            autoComplete="current-password"
          />
          <TextField
            label="New password"
            type="password"
            value={next}
            onChange={setNext}
            autoComplete="new-password"
            help="At least 10 characters."
          />
          <TextField
            label="Repeat the new password"
            type="password"
            value={repeat}
            onChange={setRepeat}
            autoComplete="new-password"
          />
          {shown !== null && (
            <p role="alert" className="form-error">
              {shown}
            </p>
          )}
          {change.isSuccess && (
            <p role="status">
              Password changed. Every other browser that was logged in has been logged out.
            </p>
          )}
          <div className="form-actions">
            <Button
              type="submit"
              variant="primary"
              disabled={change.isPending || current === '' || next === ''}
            >
              {change.isPending ? 'Saving…' : 'Change the password'}
            </Button>
          </div>
        </fieldset>
      </form>
      <Button
        onClick={() => {
          logout.mutate()
        }}
      >
        Log out
      </Button>
    </section>
  )
}
