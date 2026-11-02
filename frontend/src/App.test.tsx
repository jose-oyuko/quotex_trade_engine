import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function mockFetch(response: Response | Error) {
  const fn = vi.fn(() =>
    response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows health OK when the backend answers', async () => {
    const fetchMock = mockFetch(
      Response.json({
        status: 'ok',
        version: '0.1.0',
        environment: 'development',
        background_tasks: 0,
        database: 'ok',
        events_published: 0,
        writer: null,
        engine: { enabled: false, running: false },
      }),
    )
    render(<App />)
    expect(await screen.findByText(/Health OK/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.anything())
  })

  it('shows an error when the backend is unreachable', async () => {
    mockFetch(new Error('network down'))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('network down')
  })

  it('shows an error for an unexpected response body', async () => {
    mockFetch(Response.json({ hello: 'world' }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Unexpected health response')
  })
})
