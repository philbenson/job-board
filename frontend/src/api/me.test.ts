import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchMe, type MeBody, type RefusedBody } from './me.ts'

const TOKEN = 'header.payload.signature'

const PERSON = { id: 7 } satisfies MeBody
const REFUSED = { detail: 'sign-in required' } satisfies RefusedBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: MeBody | RefusedBody): Response {
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

describe('fetchMe', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('reports recognised for a 200 carrying the person id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(200, PERSON)),
    )

    await expect(fetchMe(TOKEN)).resolves.toBe('recognised')
  })

  it('reports refused for a 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(401, REFUSED)),
    )

    await expect(fetchMe(TOKEN)).resolves.toBe('refused')
  })

  it.each([
    ['a 503 from the service', () => answerText(503, '{"detail": "down"}')],
    ['an id on an error code', () => answer(500, PERSON)],
    ['a success code other than 200', () => answer(203, PERSON)],
    ['a 200 carrying a refusal', () => answer(200, REFUSED)],
    ['a 200 whose id is a string', () => answerText(200, '{"id": "7"}')],
    [
      'a 200 whose id is not a whole number',
      () => answerText(200, '{"id": 7.5}'),
    ],
    ['a body that does not parse', () => answerText(200, 'Signed in')],
    ['a body that is not an object', () => answerText(200, 'null')],
  ])('reports unavailable for %s', async (_case, reply) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => reply()),
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
        return answer(401, REFUSED)
      }),
    )

    await expect(fetchMe(TOKEN, controller.signal)).resolves.toBe('aborted')
  })

  it('sends the token as a bearer token through the /api prefix, cancelled by the caller signal', async () => {
    let init: RequestInit | undefined
    const fetchMock = vi.fn(async (_url: string, given?: RequestInit) => {
      init = given
      return answer(200, PERSON)
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
