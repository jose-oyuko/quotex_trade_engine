import type { ReactNode } from 'react'

export type Tone = 'good' | 'bad' | 'warn' | 'info' | 'muted'

/** A small label. The text always says the state: colour is only a second signal. */
export function Badge({
  tone = 'muted',
  children,
  title,
}: {
  tone?: Tone
  children: ReactNode
  title?: string
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  )
}
