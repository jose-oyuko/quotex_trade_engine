import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeGroup, makeSession, page } from '../../test/fixtures'
import { json, mockApi, renderWith } from '../../test/utils'
import { useGroupNames } from './useGroupNames'

afterEach(() => {
  vi.unstubAllGlobals()
})

function Names({ ids }: { ids: number[] }) {
  const name = useGroupNames()
  return (
    <ul>
      {ids.map((id) => (
        <li key={id}>{name(id)}</li>
      ))}
    </ul>
  )
}

describe('useGroupNames', () => {
  it('names the Telegram groups by their title and a session’s hidden group after the session', async () => {
    mockApi([
      ['GET', '/groups', json(page([makeGroup()]))],
      ['GET', '/sessions', json(page([makeSession({ group_id: 50 })]))],
    ])
    renderWith(<Names ids={[1, 50]} />)
    expect(await screen.findByText('Alpha signals')).toBeInTheDocument()
    expect(await screen.findByText('Session: London open')).toBeInTheDocument()
  })

  it('falls back to the group number for one it does not know', async () => {
    mockApi([
      ['GET', '/groups', json(page([]))],
      ['GET', '/sessions', json(page([]))],
    ])
    renderWith(<Names ids={[7]} />)
    expect(await screen.findByText('Group 7')).toBeInTheDocument()
  })
})
