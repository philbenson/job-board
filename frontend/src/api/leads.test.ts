import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchLeads, type Lead, type LeadsBody } from './leads.ts'

const TOKEN = 'header.payload.signature'

const LEAD = {
  posting_id: 7,
  title: 'Platform Lead',
  company: 'Example Co',
  location: null,
  url: 'https://boards.example.com/jobs/7',
  published_at: null,
  score: 5,
  reason: 'Right on target.',
  scored_at: '2026-09-02T12:00:00Z',
} satisfies Lead

const LEADS = { leads: [LEAD], total: 3 } satisfies LeadsBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: LeadsBody): Response {
  return answerText(status, JSON.stringify(body))
}

// A body outside the contract, written out on purpose.
function answerText(status: number, text: string): Response {
  return new Response(text, {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function withLead(changes: Record<string, unknown>): Response {
  return answerText(
    200,
    JSON.stringify({ leads: [{ ...LEAD, ...changes }], total: 1 }),
  )
}

// A request that never answers, and fails the way fetch does when aborted.
function answerOnlyAbort(_url: string, init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

function stubFetch(reply: (url: string, init?: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn(reply)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('fetchLeads', () => {
  it('reads the leads and their total from a 200, sending the token as a bearer token', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return answer(200, LEADS)
    })

    await expect(fetchLeads(TOKEN)).resolves.toEqual({
      kind: 'loaded',
      leads: [LEAD],
      total: 3,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/leads', expect.anything())
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${TOKEN}`,
    )
  })

  it.each([
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 503', () => answerText(503, '{"detail": "down"}')],
    ['a success code other than 200', () => answer(203, LEADS)],
    ['a body that does not parse', () => answerText(200, 'leads')],
    ['a body that is not an object', () => answerText(200, 'null')],
    ['a body without the total', () => answerText(200, '{"leads": []}')],
    ['a total that is not a whole number', () => answerText(200, '{"leads": [], "total": 1.5}')],
    ['a total below the leads it holds', () => answerText(200, JSON.stringify({ leads: [LEAD], total: 0 }))],
    ['leads that are not a list', () => answerText(200, '{"leads": {}, "total": 0}')],
    ['a lead that is not an object', () => answerText(200, '{"leads": [7], "total": 1}')],
    ['a lead without its rated date', () => withLead({ scored_at: undefined })],
    ['a rated date that is not a date', () => withLead({ scored_at: 'yesterday' })],
    ['a publish date that is not a date', () => withLead({ published_at: 'soon' })],
    ['a score in words', () => withLead({ score: 'five' })],
    ['a score below the scale', () => withLead({ score: 0 })],
    ['a score above the scale', () => withLead({ score: 6 })],
    ['a location that is not text', () => withLead({ location: 7 })],
    ['a title that is not text', () => withLead({ title: null })],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(fetchLeads(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(fetchLeads(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    let result: unknown
    void fetchLeads(TOKEN, new AbortController().signal).then((read) => {
      result = read
    })

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    stubFetch(answerOnlyAbort)
    const controller = new AbortController()

    const result = fetchLeads(TOKEN, controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
  })
})
