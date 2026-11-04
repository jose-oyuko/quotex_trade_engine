import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'
import { MIN_PASSWORD_LENGTH, passwordProblem } from '../../lib/password'
import { AuthCard } from './AuthCard'
import { setLoginState } from './session'
import { TextField } from './TextField'

/** First run: there is no owner account yet, so one is created with the code from the log. */
export function SetupPage() {
  const client = useQueryClient()
  const [code, setCode] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const setup = useMutation({
    mutationFn: () =>
      api.auth.setup({ setup_code: code.trim(), username: username.trim(), password }),
    onSuccess: (user) => {
      setLoginState(client, user)
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const found = passwordProblem(password, repeat)
    setProblem(found)
    if (found === null) setup.mutate()
  }

  return (
    <AuthCard title="Create the owner account">
      <p className="lead">
        This is the first start. Create the account that protects this dashboard: it can place
        trades and, soon, holds your Telegram and Quotex logins.
      </p>
      <form onSubmit={submit}>
        <TextField
          label="Setup code"
          value={code}
          onChange={setCode}
          autoComplete="off"
          help="Printed once in the window or log where the application runs, on the line 'owner_setup_required'. It changes every time the application starts."
        />
        <TextField
          label="Username"
          value={username}
          onChange={setUsername}
          autoComplete="username"
          help="3 to 64 letters, digits, dots, dashes or underscores."
        />
        <TextField
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          help={`At least ${String(MIN_PASSWORD_LENGTH)} characters. A few random words make a good one.`}
        />
        <TextField
          label="Repeat the password"
          type="password"
          value={repeat}
          onChange={setRepeat}
          autoComplete="new-password"
        />
        {(problem ?? (setup.isError ? errorMessage(setup.error) : null)) !== null && (
          <p role="alert" className="form-error">
            {problem ?? errorMessage(setup.error)}
          </p>
        )}
        <div className="form-actions">
          <Button
            type="submit"
            variant="primary"
            disabled={setup.isPending || code.trim() === '' || username.trim() === ''}
          >
            {setup.isPending ? 'Creating…' : 'Create the account'}
          </Button>
        </div>
      </form>
    </AuthCard>
  )
}
