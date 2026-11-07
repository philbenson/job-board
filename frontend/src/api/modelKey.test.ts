import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  type ModelKeyRefusedBody,
  type NoModelKeyBody,
  readModelKey,
  removeModelKey,
  type SavedModelKeyBody,
  saveModelKey,
} from './modelKey.ts'

const TOKEN = 'header.payload.signature'
const KEY = 'sk-ant-api03-placeholder-abcd'

const SAVED = {
  provider: 'anthropic',
  last_four: 'abcd',
  checked_at: '2026-11-07T12:00:00Z',
  usable: true,
} satisfies SavedModelKeyBody
const NONE = { detail: 'no model key saved' } satisfies NoModelKeyBody
const REJECTED = {
  detail: 'Anthropic did not accept that key.',
  reason: 'rejected',
} satisfies ModelKeyRefusedBody
const UNREACHABLE = {
  detail:
    "Anthropic did not confirm the key, so nothing was saved. Try again later; if it keeps happening, check the key's limits in the Claude Console.",
  reason: 'unavailable',
} satisfies ModelKeyRefusedBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(
  status: number,
  body: SavedModelKeyBody | NoModelKeyBody | ModelKeyRefusedBody,
): Response {
  return answerText(status, JSON.stringify(body))
}

// A body outside the contract, written out on purpose.
function answerText(status: number, text: string): Response {
  return new Response(text, {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function serviceAnswers(response: () => Response) {
  const fetchMock = vi.fn(
    async (_url: string, _init?: RequestInit) => response(),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function serviceFails() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
}

const signal = () => new AbortController().signal

describe('readModelKey', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads the saved key with the session token', async () => {
    const fetchMock = serviceAnswers(() => answer(200, SAVED))

    await expect(readModelKey(TOKEN, signal())).resolves.toEqual({
      saved: SAVED,
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/model-key')
    expect(init?.method ?? 'GET').toBe('GET')
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${TOKEN}`,
    )
  })

  it('reports none for a 404', async () => {
    serviceAnswers(() => answer(404, NONE))
    await expect(readModelKey(TOKEN, signal())).resolves.toBe('none')
  })

  it.each([
    ['a 500', () => answerText(500, '{"detail": "down"}')],
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 200 without the last four', () => answerText(200, '{"provider": "anthropic"}')],
    [
      'a 200 without whether the key is usable',
      () =>
        answerText(
          200,
          '{"provider": "anthropic", "last_four": "abcd", "checked_at": "2026-11-07T12:00:00Z"}',
        ),
    ],
    [
      'a 200 whose check time is not a time',
      () => answer(200, { ...SAVED, checked_at: 'yesterday' }),
    ],
    ['a body that is not JSON', () => answerText(200, 'not json')],
  ])('reports unavailable for %s', async (_case, response) => {
    serviceAnswers(response)
    await expect(readModelKey(TOKEN, signal())).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    serviceFails()
    await expect(readModelKey(TOKEN, signal())).resolves.toBe('unavailable')
  })
})

describe('saveModelKey', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('puts the key with the session token and answers the saved key', async () => {
    const fetchMock = serviceAnswers(() => answer(200, SAVED))

    await expect(saveModelKey(TOKEN, KEY, signal())).resolves.toEqual({
      saved: SAVED,
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/model-key')
    expect(init?.method).toBe('PUT')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe(`Bearer ${TOKEN}`)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(init?.body))).toEqual({
      provider: 'anthropic',
      key: KEY,
    })
  })

  it.each([
    ['a 422', 422, REJECTED],
    ['a 503', 503, UNREACHABLE],
  ])('passes on the sentence of %s refusal', async (_case, status, body) => {
    serviceAnswers(() => answer(status, body))
    await expect(saveModelKey(TOKEN, KEY, signal())).resolves.toEqual({
      refused: body.detail,
    })
  })

  it.each([
    [
      'a 422 listing problems with the body',
      () =>
        answerText(
          422,
          '{"detail": [{"type": "missing", "loc": ["body", "provider"], "msg": "Field required"}]}',
        ),
    ],
    ['a 500', () => answerText(500, '{"detail": "down"}')],
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 200 outside the contract', () => answerText(200, '{}')],
    ['a body that is not JSON', () => answerText(503, 'Service Unavailable')],
  ])('reports unavailable for %s', async (_case, response) => {
    serviceAnswers(response)
    await expect(saveModelKey(TOKEN, KEY, signal())).resolves.toBe(
      'unavailable',
    )
  })

  it('reports unavailable when the request fails', async () => {
    serviceFails()
    await expect(saveModelKey(TOKEN, KEY, signal())).resolves.toBe(
      'unavailable',
    )
  })
})

describe('removeModelKey', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('deletes the key with the session token', async () => {
    const fetchMock = serviceAnswers(() => new Response(null, { status: 204 }))

    await expect(removeModelKey(TOKEN, signal())).resolves.toBe('removed')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/model-key')
    expect(init?.method).toBe('DELETE')
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${TOKEN}`,
    )
  })

  it('reports unavailable for any other answer', async () => {
    serviceAnswers(() => answerText(500, '{"detail": "down"}'))
    await expect(removeModelKey(TOKEN, signal())).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    serviceFails()
    await expect(removeModelKey(TOKEN, signal())).resolves.toBe('unavailable')
  })
})
