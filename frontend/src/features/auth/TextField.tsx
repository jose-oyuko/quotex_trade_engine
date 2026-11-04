import { useId } from 'react'

/** A labelled input for the auth forms (the label is what a screen reader and the tests find). */
export function TextField({
  label,
  value,
  onChange,
  type = 'text',
  autoComplete,
  help,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'password'
  autoComplete?: string
  help?: string
}) {
  const id = useId()
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        aria-describedby={help ? `${id}-help` : undefined}
        onChange={(event) => {
          onChange(event.target.value)
        }}
      />
      {help && (
        <small id={`${id}-help`} className="help">
          {help}
        </small>
      )}
    </div>
  )
}
