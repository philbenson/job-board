import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchProfile,
  saveTargetTitles,
  type ProfileBody,
  type SaveRefusalBody,
  type TargetTitlesBody,
} from './profile.ts'
import { profileWith } from '../test/profileAnswers.ts'

const TOKEN = 'header.payload.signature'

const PROFILE = profileWith(['Designer', 'Writer'])
const TOO_LONG = {
  detail: [
    {
      loc: ['body', 'titles', 0],
      msg: 'A target title can be at most 100 characters',
      type: 'target_title_too_long',
      input: 'x'.repeat(101),
    },
  ],
} satisfies SaveRefusalBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: ProfileBody | SaveRefusalBody): Response {
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

function stubFetch(reply: (url: string, init?: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn(reply)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('fetchProfile', () => {
  it('reads the target titles from a 200, sending the token as a bearer token', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return answer(200, PROFILE)
    })

    await expect(fetchProfile(TOKEN)).resolves.toEqual({
      kind: 'loaded',
      titles: ['Designer', 'Writer'],
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/profile', expect.anything())
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${TOKEN}`,
    )
  })

  it.each([
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 503', () => answerText(503, '{"detail": "down"}')],
    ['a success code other than 200', () => answer(203, PROFILE)],
    ['a 200 without the titles', () => answerText(200, '{}')],
    ['a 200 whose titles are not a list', () => answerText(200, '{"target_titles": "Designer"}')],
    ['a 200 whose titles are not all text', () => answerText(200, '{"target_titles": ["a", 7]}')],
    ['a body that does not parse', () => answerText(200, 'Designer')],
    ['a body that is not an object', () => answerText(200, 'null')],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(fetchProfile(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(fetchProfile(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    let result: unknown
    void fetchProfile(TOKEN, new AbortController().signal).then((read) => {
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

    const result = fetchProfile(TOKEN, controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
  })
})

describe('saveTargetTitles', () => {
  it('puts the whole list as JSON with the bearer token and reads back the stored titles', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return answer(200, profileWith(['Designer']))
    })

    await expect(
      saveTargetTitles(TOKEN, ['Designer', ' designer ']),
    ).resolves.toEqual({ kind: 'saved', titles: ['Designer'] })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/profile/target-titles',
      expect.anything(),
    )
    expect(init?.method).toBe('PUT')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe(`Bearer ${TOKEN}`)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(JSON.parse(init?.body as string)).toEqual({
      titles: ['Designer', ' designer '],
    } satisfies TargetTitlesBody)
  })

  it("reports the backend's rule for a 422 and the sent title it names", async () => {
    stubFetch(async () => answer(422, TOO_LONG))

    await expect(saveTargetTitles(TOKEN, ['x'.repeat(101)])).resolves.toEqual({
      kind: 'refused',
      message: 'A target title can be at most 100 characters',
      title: 'x'.repeat(101),
    })
  })

  it.each([
    ['the whole list', ['body', 'titles']],
    ['an index past the list sent', ['body', 'titles', 1]],
    ['an index that is not a number', ['body', 'titles', '0']],
    ['another field', ['body', 'salary', 0]],
  ])('names no title for a 422 about %s', async (_case, loc) => {
    const refusal = {
      detail: [{ loc, msg: 'You can list at most 20 target titles', type: 'target_titles_too_many' }],
    } satisfies SaveRefusalBody
    stubFetch(async () => answer(422, refusal))

    await expect(saveTargetTitles(TOKEN, ['Designer'])).resolves.toEqual({
      kind: 'refused',
      message: 'You can list at most 20 target titles',
      title: null,
    })
  })

  it.each([
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 500', () => answerText(500, 'Internal Server Error')],
    ['a 200 without the titles', () => answerText(200, '{}')],
    ['a 422 without a detail list', () => answerText(422, '{"detail": "no"}')],
    ['a 422 with an empty detail list', () => answerText(422, '{"detail": []}')],
    ['a 422 whose first entry has no message', () => answerText(422, '{"detail": [{"loc": []}]}')],
    ['a 422 that does not parse', () => answerText(422, 'Unprocessable')],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(saveTargetTitles(TOKEN, ['Designer'])).resolves.toBe(
      'unavailable',
    )
  })

  it('gives up after five seconds and reports unavailable', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    let result: unknown
    void saveTargetTitles(TOKEN, ['Designer']).then((saved) => {
      result = saved
    })

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it('reports aborted, not saved, for an answer that lands after the caller aborts', async () => {
    const controller = new AbortController()
    stubFetch(async () => {
      controller.abort()
      return answer(200, PROFILE)
    })

    await expect(
      saveTargetTitles(TOKEN, ['Designer'], controller.signal),
    ).resolves.toBe('aborted')
  })
})
