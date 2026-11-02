import type { AccountType } from '../../api/types'

/** DEMO or REAL, unmistakable: real money is red and says so in words. */
export function AccountBadge({ account }: { account: AccountType }) {
  return account === 'real' ? (
    <span className="account account-real" role="status">
      REAL MONEY
    </span>
  ) : (
    <span className="account account-demo" role="status">
      DEMO
    </span>
  )
}
