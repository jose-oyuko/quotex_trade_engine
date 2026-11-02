import { useEffect, useId, useRef, type ReactNode } from 'react'

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * An accessible modal dialog: it labels itself, puts focus inside, keeps Tab inside, closes on
 * Escape and gives focus back to what had it. (The native dialog element is not used because
 * browsers and test environments still differ on it.)
 */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const first = panel.current?.querySelector<HTMLElement>('[data-autofocus]')
    const target = first ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE) ?? panel.current
    target?.focus()
    return () => {
      previous?.focus()
    }
  }, [])

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || panel.current === null) return
    const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
    const firstItem = items[0]
    const lastItem = items[items.length - 1]
    if (firstItem === undefined || lastItem === undefined) return
    if (event.shiftKey && document.activeElement === firstItem) {
      event.preventDefault()
      lastItem.focus()
    } else if (!event.shiftKey && document.activeElement === lastItem) {
      event.preventDefault()
      firstItem.focus()
    }
  }

  return (
    <div className="modal-backdrop">
      {/* the keyboard handler lives on the dialog itself, which is where focus is kept */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div
        ref={panel}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  )
}
