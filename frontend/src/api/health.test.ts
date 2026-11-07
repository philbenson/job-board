import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHealth, type HealthBody } from './health.ts'

const OK = { status: 'ok', database: 'ok' } satisfies HealthBody
const UNAVAILABLE = {
  status: 'unavailable',
  database: 'unreachable',
} satisfies HealthBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: HealthBody): Response {
  return answerText(status, JSON.stringify(body))
}

// A body outside the contract, written out on purpose.
function answerText(status: number, text: string): Response {
  return new Response(text, {
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
      vi.fn(async () => answer(200, OK)),
    )

    await expect(fetchHealth()).resolves.toBe('ok')
  })

  it.each([
    ['a 503 from the service', () => answer(503, UNAVAILABLE)],
    ['a status of ok on an error code', () => answer(500, OK)],
    ['a success code other than 200', () => answer(203, OK)],
    [
      'a 200 with a status outside the contract',
      () => answerText(200, '{"status": "degraded"}'),
    ],
    ['a body that does not parse', () => answerText(200, 'Service is fine')],
    ['a body that is not an object', () => answerText(200, 'null')],
  ])('reports unavailable for %s', async (_case, reply) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => reply()),
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
      return answer(200, OK)
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
