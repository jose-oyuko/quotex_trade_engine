import { useMutation } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { AccountType, DerivAccount, SecretsOut } from '../../api/types'
import { Button } from '../../components/Button'
import { Money } from '../../components/Money'
import { errorMessage } from '../../lib/errors'
import { SecretRow } from './SecretsPanel'

function CheckResult({ account }: { account: DerivAccount }) {
  const kind = account.account_type === 'demo' ? 'a demo account' : 'a REAL MONEY account'
  return (
    <p role="status">
      This token opens account <strong>{account.account_id}</strong>, {kind}
      {account.currency !== null && <>, in {account.currency}</>}
      {account.balance !== null && (
        <>
          , balance <Money value={account.balance} />
        </>
      )}
      . Nothing was traded.
    </p>
  )
}

function CheckButton({ accountType, ready }: { accountType: AccountType; ready: boolean }) {
  const check = useMutation({ mutationFn: () => api.deriv.check(accountType) })
  const label = accountType === 'demo' ? 'Check the demo token' : 'Check the real token'
  return (
    <div>
      <div className="form-actions">
        <Button
          disabled={!ready || check.isPending}
          onClick={() => {
            check.mutate()
          }}
        >
          {check.isPending ? 'Asking Deriv…' : label}
        </Button>
      </div>
      {check.isSuccess && <CheckResult account={check.data} />}
      {check.isError && (
        <p role="alert" className="form-error">
          {errorMessage(check.error)}
        </p>
      )}
    </div>
  )
}

/**
 * Deriv's logins (decisions D-74, D-76): the app id and one token per account, stored encrypted
 * like the Quotex password. *Check* asks Deriv which account a token opens, without trading.
 */
export function DerivPanel({ data }: { data: SecretsOut }) {
  const keyOk = data.key === 'ok'
  const items = data.items.filter((item) => item.group === 'deriv')
  const stored = (name: string) =>
    items.some((item) => item.name === name && item.is_set && item.readable)
  const appId = stored('deriv_app_id')
  return (
    <fieldset>
      <legend>Deriv</legend>
      <p className="help">
        Register an application on{' '}
        <a href="https://developers.deriv.com" target="_blank" rel="noreferrer">
          Deriv’s developer site
        </a>{' '}
        to get an app id. Then, in your Deriv account, create a token for the demo account (and, if
        you want, one for the real account) with{' '}
        <strong>only the Read and Trade permissions</strong>: never Payments or Admin. Restart the
        engine after changing one.
      </p>
      <ul className="secret-list">
        {items.map((item) => (
          <SecretRow key={item.name} item={item} keyOk={keyOk} />
        ))}
      </ul>
      <CheckButton accountType="demo" ready={appId && stored('deriv_token_demo')} />
      {stored('deriv_token_real') && <CheckButton accountType="real" ready={appId} />}
    </fieldset>
  )
}
