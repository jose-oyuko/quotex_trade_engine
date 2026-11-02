import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Countdown } from './Countdown'

beforeEach(() => {
  vi.useFakeTimers({ now: new Date('2026-11-02T10:00:00Z') })
})
afterEach(() => {
  vi.useRealTimers()
})

describe('Countdown', () => {
  it('counts down to the expiry, once a second', () => {
    render(<Countdown until="2026-11-02T10:01:05Z" />)
    expect(screen.getByText('1:05')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(screen.getByText('1:00')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(59_000)
    })
    expect(screen.getByText('0:01')).toBeInTheDocument()
  })

  it('says settling once the time has passed, and does not go negative', () => {
    render(<Countdown until="2026-11-02T10:00:10Z" />)
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(screen.getByText('settling…')).toBeInTheDocument()
  })

  it('shows a dash when there is no expiry or it is not a time', () => {
    const { rerender } = render(<Countdown until={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    rerender(<Countdown until="soon" />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('stops its timer when removed', () => {
    const { unmount } = render(<Countdown until="2026-11-02T10:05:00Z" />)
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
