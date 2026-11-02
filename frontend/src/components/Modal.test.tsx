import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Modal } from './Modal'

function Harness({ onClose = vi.fn() }: { onClose?: () => void }) {
  return (
    <>
      <button>outside</button>
      <Modal title="Are you sure?" onClose={onClose}>
        <button>first</button>
        <input aria-label="middle" />
        <button>last</button>
      </Modal>
    </>
  )
}

describe('Modal', () => {
  it('is a labelled modal dialog', () => {
    render(<Harness />)
    const dialog = screen.getByRole('dialog', { name: 'Are you sure?' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })

  it('moves focus inside when it opens', () => {
    render(<Harness />)
    expect(screen.getByRole('button', { name: 'first' })).toHaveFocus()
  })

  it('keeps Tab and Shift+Tab inside the dialog', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.tab()
    expect(screen.getByLabelText('middle')).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'last' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'first' })).toHaveFocus() // wrapped, not "outside"
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'last' })).toHaveFocus()
  })

  it('asks to close on Escape', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<Harness onClose={onClose} />)
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('gives focus back to what had it before', () => {
    const { rerender } = render(<button>opener</button>)
    screen.getByRole('button', { name: 'opener' }).focus()
    expect(screen.getByRole('button', { name: 'opener' })).toHaveFocus()
    rerender(
      <>
        <button>opener</button>
        <Modal title="t" onClose={() => undefined}>
          <button>inside</button>
        </Modal>
      </>,
    )
    expect(screen.getByRole('button', { name: 'inside' })).toHaveFocus()
    rerender(<button>opener</button>)
    expect(screen.getByRole('button', { name: 'opener' })).toHaveFocus()
  })
})
