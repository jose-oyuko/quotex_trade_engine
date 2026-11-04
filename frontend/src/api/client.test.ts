import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, onUnauthorized, reportCsvUrl, request } from './client'

function mockFetch(response: Response | Error) {
  const fn = vi.fn<typeof fetch>(() =>
    response instanceof Response ? Promise.resolve(response.clone()) : Promise.reject(response),
  )
  vi.stubGlobal('fetch', fn)
  return fn
}

function lastCall(fn: ReturnType<typeof mockFetch>) {
  const call = fn.mock.calls.at(-1)
  if (call === undefined) throw new Error('fetch was not called')
  const url = call[0]
  if (typeof url !== 'string') throw new Error('expected the URL as a string')
  return { url, init: call[1] ?? {} }
}

describe('request', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends a GET to /api/v1 and returns the JSON', async () => {
    const fetchMock = mockFetch(Response.json({ hello: 'world' }))
    expect(await request('GET', '/anything')).toEqual({ hello: 'world' })
    const { url, init } = lastCall(fetchMock)
    expect(url).toBe('/api/v1/anything')
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
  })

  it('writes the query string and leaves out what is not set', async () => {
    const fetchMock = mockFetch(Response.json({}))
    await request('GET', '/trades', {
      query: { status: 'won', limit: 20, offset: 0, group_id: undefined, account_type: null },
    })
    expect(lastCall(fetchMock).url).toBe('/api/v1/trades?status=won&limit=20&offset=0')
  })

  it('sends a body as JSON', async () => {
    const fetchMock = mockFetch(Response.json({}))
    await request('PUT', '/risk/limits', { body: { max_stake: '5.00' } })
    const { init } = lastCall(fetchMock)
    expect(init.body).toBe('{"max_stake":"5.00"}')
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' })
  })

  it('returns nothing for a 204', async () => {
    mockFetch(new Response(null, { status: 204 }))
    expect(await request('DELETE', '/groups/1')).toBeUndefined()
  })

  it('turns the error body into an ApiError', async () => {
    mockFetch(
      Response.json(
        { error: { code: 'group_exists', message: 'a group for that chat exists', details: null } },
        { status: 409 },
      ),
    )
    const error = await request('POST', '/groups').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 409,
      code: 'group_exists',
      message: 'a group for that chat exists',
    })
  })

  it('keeps the field problems of a validation error', async () => {
    const details = [{ field: 'settings.base_stake', message: 'must be greater than 0' }]
    mockFetch(
      Response.json(
        { error: { code: 'validation_error', message: 'The request is not valid.', details } },
        { status: 422 },
      ),
    )
    const error = await request('POST', '/groups').catch((e: unknown) => e)
    expect(error).toMatchObject({ code: 'validation_error', details })
  })

  it('copes with an error answer that is not our error body', async () => {
    mockFetch(new Response('<html>Bad gateway</html>', { status: 502 }))
    const error = await request('GET', '/status').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 502, code: 'http_error' })
  })

  it('says so when the backend cannot be reached', async () => {
    mockFetch(new TypeError('fetch failed'))
    await expect(request('GET', '/status')).rejects.toThrow('Cannot reach the backend')
  })

  it('lets an abort through unchanged', async () => {
    mockFetch(new DOMException('aborted', 'AbortError'))
    await expect(request('GET', '/status')).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('a lost session', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const refusal = (code: string) =>
    Response.json({ error: { code, message: 'no', details: null } }, { status: 401 })

  it('is reported once so the app can show the login page', async () => {
    mockFetch(refusal('not_authenticated'))
    const handler = vi.fn()
    const stop = onUnauthorized(handler)
    await expect(request('GET', '/status')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledTimes(1)
    stop()
  })

  it('is not what a wrong password looks like', async () => {
    mockFetch(refusal('invalid_login'))
    const handler = vi.fn()
    const stop = onUnauthorized(handler)
    await expect(api.auth.login({ username: 'a', password: 'b' })).rejects.toMatchObject({
      code: 'invalid_login',
    })
    expect(handler).not.toHaveBeenCalled()
    stop()
  })

  it('stops being reported once the handler is removed', async () => {
    mockFetch(refusal('not_authenticated'))
    const handler = vi.fn()
    onUnauthorized(handler)()
    await expect(request('GET', '/status')).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('sends the login to the right endpoints', async () => {
    const fetchMock = mockFetch(Response.json({ username: 'a', role: 'admin' }))
    await api.auth.login({ username: 'a', password: 'b' })
    expect(lastCall(fetchMock).url).toBe('/api/v1/auth/login')
    expect(lastCall(fetchMock).init.method).toBe('POST')
    await api.auth.state()
    expect(lastCall(fetchMock).url).toBe('/api/v1/auth/state')
  })
})

describe('api', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each([
    ['status', () => api.status(), 'GET', '/api/v1/status'],
    ['groups.list', () => api.groups.list({ limit: 10 }), 'GET', '/api/v1/groups?limit=10'],
    ['groups.pause', () => api.groups.pause(3), 'POST', '/api/v1/groups/3/pause'],
    ['groups.resume', () => api.groups.resume(3), 'POST', '/api/v1/groups/3/resume'],
    ['groups.remove', () => api.groups.remove(3), 'DELETE', '/api/v1/groups/3'],
    ['groups.risk', () => api.groups.risk(3), 'GET', '/api/v1/groups/3/risk'],
    ['chains.end', () => api.chains.end('abc'), 'POST', '/api/v1/chains/abc/end'],
    [
      'chains.stopAfterCurrent',
      () => api.chains.stopAfterCurrent('abc'),
      'POST',
      '/api/v1/chains/abc/stop-after-current',
    ],
    [
      'trades.list',
      () => api.trades.list({ status: 'won', group_id: 2 }),
      'GET',
      '/api/v1/trades?status=won&group_id=2',
    ],
    ['signals.get', () => api.signals.get('s1'), 'GET', '/api/v1/signals/s1'],
    ['risk.events', () => api.risk.events({ offset: 50 }), 'GET', '/api/v1/risk/events?offset=50'],
    ['killSwitch.release', () => api.killSwitch.release(), 'DELETE', '/api/v1/kill-switch'],
    ['account.get', () => api.account.get(), 'GET', '/api/v1/account'],
    [
      'reports.summary',
      () => api.reports.summary({ account_type: 'demo' }),
      'GET',
      '/api/v1/reports/summary?account_type=demo',
    ],
    [
      'reports.breakdown',
      () =>
        api.reports.breakdown('hour', {
          account_type: 'real',
          from: '2026-11-01T00:00:00.000Z',
          group_id: 2,
          utc_offset_minutes: -180,
        }),
      'GET',
      '/api/v1/reports/breakdown?account_type=real&from=2026-11-01T00%3A00%3A00.000Z&group_id=2&utc_offset_minutes=-180&by=hour',
    ],
    [
      'reports.equity',
      () => api.reports.equity({ account_type: 'demo' }),
      'GET',
      '/api/v1/reports/equity?account_type=demo',
    ],
    [
      'reports.depth',
      () => api.reports.depth({ account_type: 'demo', asset: 'EURUSD' }),
      'GET',
      '/api/v1/reports/depth?account_type=demo&asset=EURUSD',
    ],
  ])('%s calls %s %s', async (_name, call, method, url) => {
    const fetchMock = mockFetch(Response.json({}))
    await call()
    const sent = lastCall(fetchMock)
    expect(sent.init.method).toBe(method)
    expect(sent.url).toBe(url)
  })

  it('engages the kill switch with the choice to end the running chains', async () => {
    const fetchMock = mockFetch(Response.json({}))
    await api.killSwitch.engage(true)
    expect(lastCall(fetchMock).init.body).toBe('{"stop_chains":true}')
    await api.killSwitch.engage()
    expect(lastCall(fetchMock).init.body).toBe('{"stop_chains":false}')
  })

  it('switches the account with the type in the body', async () => {
    const fetchMock = mockFetch(Response.json({}))
    await api.account.set('real')
    const { init } = lastCall(fetchMock)
    expect(init.method).toBe('PUT')
    expect(init.body).toBe('{"account_type":"real"}')
  })
})

describe('reportCsvUrl', () => {
  it('addresses the trades file, with the filters and the separator', () => {
    expect(reportCsvUrl('trades', { account_type: 'demo', group_id: 3 }, 'semicolon')).toBe(
      '/api/v1/reports/export/trades.csv?account_type=demo&group_id=3&delimiter=semicolon',
    )
  })

  it('addresses a breakdown file, saying what to split by', () => {
    expect(reportCsvUrl('weekday', { account_type: 'real', utc_offset_minutes: 60 })).toBe(
      '/api/v1/reports/export/breakdown.csv?account_type=real&utc_offset_minutes=60&by=weekday&delimiter=comma',
    )
  })

  it('leaves out filters that are not set', () => {
    const url = reportCsvUrl('trades', { account_type: 'demo', asset: undefined })
    expect(url).not.toContain('asset')
    expect(url).not.toContain('from')
  })
})
