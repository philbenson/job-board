import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchMe } from './me.ts'

const TOKEN = 'header.payload.signature'

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

describe('fetchMe', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('reports recognised for a 200 carrying the person id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(200, '{"id": 7}')),
    )

    await expect(fetchMe(TOKEN)).resolves.toBe('recognised')
  })

  it('reports refused for a 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(401, '{"detail": "sign-in required"}')),
    )

    await expect(fetchMe(TOKEN)).resolves.toBe('refused')
  })

  it.each([
    ['a 503 from the service', 503, '{"detail": "unavailable"}'],
    ['an id on an error code', 500, '{"id": 7}'],
    ['a success code other than 200', 203, '{"id": 7}'],
    ['a 200 without an id', 200, '{"detail": "ok"}'],
    ['a 200 whose id is a string', 200, '{"id": "7"}'],
    ['a 200 whose id is not a whole number', 200, '{"id": 7.5}'],
    ['a body that does not parse', 200, 'Signed in'],
    ['a body that is not an object', 200, 'null'],
  ])('reports unavailable for %s', async (_case, status, body) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(status, body)),
    )

    await expect(fetchMe(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    await expect(fetchMe(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(answerOnlyAbort))
    let result: string | undefined
    void fetchMe(TOKEN, new AbortController().signal).then((me) => {
      result = me
    })

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    vi.stubGlobal('fetch', vi.fn(answerOnlyAbort))
    const controller = new AbortController()

    const result = fetchMe(TOKEN, controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
  })

  it('reports aborted, not refused, for an answer that lands after the caller aborts', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        controller.abort()
        return answer(401, '{"detail": "sign-in required"}')
      }),
    )

    await expect(fetchMe(TOKEN, controller.signal)).resolves.toBe('aborted')
  })

  it('sends the token as a bearer token through the /api prefix, cancelled by the caller signal', async () => {
    let init: RequestInit | undefined
    const fetchMock = vi.fn(async (_url: string, given?: RequestInit) => {
      init = given
      return answer(200, '{"id": 7}')
    })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await fetchMe(TOKEN, controller.signal)
    expect(fetchMock).toHaveBeenCalledWith('/api/me', expect.anything())
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${TOKEN}`,
    )
    expect(init?.signal?.aborted).toBe(false)
    controller.abort()

    expect(init?.signal?.aborted).toBe(true)
  })
})
