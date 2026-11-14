import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createIncident, resetHealth, serverUp, waitForServer } from './api'
import { fixtureIncident } from './fixtures'

const ok = (body: unknown = { ok: true }) => new Response(JSON.stringify(body), { status: 200 })
const down = () => Promise.reject(new TypeError('Failed to fetch'))
const fast = { budgetMs: 300, quickMs: 50 }

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  resetHealth()
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

const urls = () => fetchMock.mock.calls.map(([u]) => String(u))

describe('serverUp', () => {
  it('is true when /health answers ok, and caches the success', async () => {
    fetchMock.mockResolvedValue(ok())
    expect(await serverUp()).toBe(true)
    expect(await serverUp()).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(urls()[0]).toMatch(/\/health$/)
  })

  it('does not cache a failure: a sleeping server is checked again', async () => {
    fetchMock.mockImplementationOnce(down).mockResolvedValueOnce(ok())
    expect(await serverUp()).toBe(false)
    expect(await serverUp()).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('is false on a non-2xx /health', async () => {
    fetchMock.mockResolvedValue(new Response('waking', { status: 503 }))
    expect(await serverUp()).toBe(false)
  })
})

describe('waitForServer', () => {
  it('retries until the server wakes, and reports waking once', async () => {
    fetchMock.mockImplementationOnce(down).mockImplementationOnce(down).mockResolvedValueOnce(ok())
    const onWaking = vi.fn()
    expect(await waitForServer(onWaking, { budgetMs: 5000, quickMs: 50 })).toBe(true)
    expect(onWaking).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('gives up after the budget', async () => {
    fetchMock.mockImplementation(down)
    expect(await waitForServer(undefined, fast)).toBe(false)
  })
})

describe('createIncident', () => {
  it('sends nothing in demo mode', async () => {
    const r = await createIncident('note', true)
    expect(r).toEqual({ live: false, incident_id: fixtureIncident.id, reason: 'demo' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('posts the note to /incidents once the server is up', async () => {
    fetchMock.mockResolvedValueOnce(ok()).mockResolvedValueOnce(ok({ incident_id: 'abc-123' }))
    const r = await createIncident('65M chest pain, Suite 1800', false, undefined, fast)
    expect(r).toEqual({ live: true, incident_id: 'abc-123' })
    const [url, init] = fetchMock.mock.calls[1]
    expect(String(url)).toMatch(/\/incidents$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ note: '65M chest pain, Suite 1800' })
  })

  it('waits for a sleeping server instead of falling back straight away', async () => {
    fetchMock.mockImplementationOnce(down).mockResolvedValueOnce(ok()).mockResolvedValueOnce(ok({ incident_id: 'woke' }))
    const onWaking = vi.fn()
    const r = await createIncident('note', false, onWaking, { budgetMs: 5000, quickMs: 50 })
    expect(r).toEqual({ live: true, incident_id: 'woke' })
    expect(onWaking).toHaveBeenCalledTimes(1)
  })

  it('falls back to the sample incident only after the server stays down', async () => {
    fetchMock.mockImplementation(down)
    const r = await createIncident('note', false, undefined, fast)
    expect(r).toEqual({ live: false, incident_id: fixtureIncident.id, reason: 'unreachable' })
    expect(urls().every((u) => u.endsWith('/health'))).toBe(true)
  })

  it('surfaces a server error instead of hiding it', async () => {
    fetchMock.mockResolvedValueOnce(ok()).mockResolvedValueOnce(new Response('boom', { status: 500 }))
    await expect(createIncident('note', false, undefined, fast)).rejects.toThrow(/500/)
  })
})
