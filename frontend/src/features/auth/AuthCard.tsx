import type { ReactNode } from 'react'

/** The centred box the login, setup and loading screens share. */
export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-heading">
        <p className="brand">Quotex Trade Engine</p>
        <h1 id="auth-heading">{title}</h1>
        {children}
      </section>
    </main>
  )
}
