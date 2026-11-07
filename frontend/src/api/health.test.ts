import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHealth } from './health.ts'

function answer(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('fetchHealth', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reports ok for a 200 whose status is ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(200, '{"status": "ok", "database": "ok"}')),
    )

    await expect(fetchHealth()).resolves.toBe('ok')
  })

  it.each([
    [
      'a 503 from the service',
      503,
      '{"status": "unavailable", "database": "unreachable"}',
    ],
    ['a 200 with another status', 200, '{"status": "degraded"}'],
    ['a status of ok on an error code', 500, '{"status": "ok"}'],
    ['a body that does not parse', 200, 'Service is fine'],
    ['a body that is not an object', 200, 'null'],
  ])('reports unavailable for %s', async (_case, status, body) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(status, body)),
    )

    await expect(fetchHealth()).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    await expect(fetchHealth()).resolves.toBe('unavailable')
  })

  it('asks the service through the /api prefix with the caller signal', async () => {
    const fetchMock = vi.fn(async () =>
      answer(200, '{"status": "ok", "database": "ok"}'),
    )
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await fetchHealth(controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ signal: controller.signal }),
    )
  })
})
