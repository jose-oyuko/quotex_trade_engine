import type { ButtonHTMLAttributes } from 'react'

type Variant = 'default' | 'primary' | 'danger' | 'quiet'

export function Button({
  variant = 'default',
  className = '',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type={type} className={`btn btn-${variant} ${className}`.trim()} {...props} />
}
