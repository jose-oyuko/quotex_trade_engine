import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { errorMessage } from '../../lib/errors'
import { AuthCard } from './AuthCard'
import { setLoginState } from './session'
import { TextField } from './TextField'

export function LoginPage() {
  const client = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({
    mutationFn: () => api.auth.login({ username: username.trim(), password }),
    onSuccess: (user) => {
      setLoginState(client, user)
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    login.mutate()
  }

  return (
    <AuthCard title="Log in">
      <form onSubmit={submit}>
        <TextField
          label="Username"
          value={username}
          onChange={setUsername}
          autoComplete="username"
        />
        <TextField
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        {login.isError && (
          <p role="alert" className="form-error">
            {errorMessage(login.error)}
          </p>
        )}
        <div className="form-actions">
          <Button
            type="submit"
            variant="primary"
            disabled={login.isPending || username.trim() === '' || password === ''}
          >
            {login.isPending ? 'Logging in…' : 'Log in'}
          </Button>
        </div>
        <p className="help">
          Forgot the password? On the computer that runs the application, run{' '}
          <code>npm run owner:reset</code>.
        </p>
      </form>
    </AuthCard>
  )
}
