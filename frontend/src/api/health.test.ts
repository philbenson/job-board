import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHealth } from './health.ts'

function answer(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// A request that never answers, and fails the way fetch does when aborted.
function answerOnlyAbort(_url: string, init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

describe('fetchHealth', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(answerOnlyAbort))
    let result: string | undefined
    void fetchHealth(new AbortController().signal).then((health) => {
      result = health
    })

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    vi.stubGlobal('fetch', vi.fn(answerOnlyAbort))
    const controller = new AbortController()

    const result = fetchHealth(controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
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
    ['a success code other than 200', 203, '{"status": "ok"}'],
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

  it('asks the service through the /api prefix, cancelled by the caller signal', async () => {
    let requestSignal: AbortSignal | null | undefined
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      requestSignal = init?.signal
      return answer(200, '{"status": "ok", "database": "ok"}')
    })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await fetchHealth(controller.signal)
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.anything())
    expect(requestSignal?.aborted).toBe(false)
    controller.abort()

    expect(requestSignal?.aborted).toBe(true)
  })
})
