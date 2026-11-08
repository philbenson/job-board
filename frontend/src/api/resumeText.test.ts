import { afterEach, describe, expect, it, vi } from 'vitest'
import type { StorageRefusalBody } from './resume.ts'
import {
  fetchResumeText,
  saveResumeText,
  type CheckedTextBody,
  type ResumeTextBody,
  type TextRefusalBody,
} from './resumeText.ts'

const TOKEN = 'header.payload.signature'
// Microseconds the browser's Date cannot hold, which must go back as they came.
const UPLOADED_AT = '2026-11-07T20:29:59.747970Z'
const CHECKED_AT = '2026-11-07T21:00:00.123456Z'
const TEXT = 'Avery Example\nStaff Engineer, Example Widgets\n\nLed the move to small services.'

const FOUND = {
  uploaded_at: UPLOADED_AT,
  state: 'found',
  text: TEXT,
  checked_at: null,
} satisfies ResumeTextBody
const CHECKED = { ...FOUND, checked_at: CHECKED_AT } satisfies ResumeTextBody
const NO_RESUME = { detail: 'No resume uploaded' } satisfies StorageRefusalBody
const REPLACED = {
  detail: 'Your resume was replaced since this text was read',
} satisfies StorageRefusalBody
const TOO_LONG = {
  detail: [
    {
      type: 'resume_text_too_long',
      loc: ['body', 'text'],
      msg: 'The resume text can be at most 15,000 characters',
    },
  ],
} satisfies TextRefusalBody
const NOT_SET_UP = { detail: 'Resume storage is not set up' } satisfies StorageRefusalBody
const DID_NOT_ANSWER = {
  detail: 'Resume storage did not answer; try again later',
} satisfies StorageRefusalBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: ResumeTextBody | StorageRefusalBody | TextRefusalBody): Response {
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

// Resolves to what `start` resolves to, recording whether it has yet.
function watched<T>(start: () => Promise<T>): { result: T | undefined } {
  const seen: { result: T | undefined } = { result: undefined }
  void start().then((result) => {
    seen.result = result
  })
  return seen
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// The answers both routes give alike when storage, or anything else, is why they cannot.
const STORAGE_ANSWERS = [
  ['a 503 saying storage is not set up', 'not set up', () => answer(503, NOT_SET_UP)],
  ['a 503 saying storage did not answer', 'storage down', () => answer(503, DID_NOT_ANSWER)],
  ['a 503 saying something else', 'unavailable', () => answerText(503, '{"detail": "down"}')],
  ['a 404', 'no resume', () => answer(404, NO_RESUME)],
  ['a 401', 'unavailable', () => answerText(401, '{"detail": "sign-in required"}')],
  ['a 500', 'unavailable', () => answerText(500, 'Internal Server Error')],
] as const

describe('fetchResumeText', () => {
  it('reads the text from a 200 with the bearer token, keeping the upload time as sent', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(answer(200, CHECKED)))

    const read = await fetchResumeText(TOKEN)

    expect(read).toEqual({
      kind: 'loaded',
      resumeText: {
        uploadedAt: UPLOADED_AT,
        state: 'found',
        text: TEXT,
        checkedAt: new Date(CHECKED_AT),
      },
    })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/resume/text')
    expect(init?.method).toBeUndefined()
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${TOKEN}`)
  })

  it.each(['cut', 'none_found', 'failed', null] as const)(
    'reads the state %s',
    async (state) => {
      const body = { ...FOUND, state, text: state === 'cut' ? TEXT : null } satisfies ResumeTextBody
      stubFetch(() => Promise.resolve(answer(200, body)))

      const read = await fetchResumeText(TOKEN)

      expect(read).toMatchObject({ kind: 'loaded', resumeText: { state, checkedAt: null } })
    },
  )

  it.each(STORAGE_ANSWERS)('reports %s as %s', async (_case, outcome, reply) => {
    stubFetch(() => Promise.resolve(reply()))

    await expect(fetchResumeText(TOKEN)).resolves.toBe(outcome)
  })

  it.each([
    ['a body that is not an object', '"found"'],
    ['no upload time', JSON.stringify({ ...FOUND, uploaded_at: undefined })],
    ['an upload time that is not a time', JSON.stringify({ ...FOUND, uploaded_at: 'soon' })],
    ['a state it does not know', JSON.stringify({ ...FOUND, state: 'scanned' })],
    ['no state at all', JSON.stringify({ ...FOUND, state: undefined })],
    ['text that is not text', JSON.stringify({ ...FOUND, text: 7 })],
    ['a check time that is not a time', JSON.stringify({ ...FOUND, checked_at: 'yesterday' })],
    ['a body that does not parse', '{'],
  ])('reports unavailable for a 200 with %s', async (_case, body) => {
    stubFetch(() => Promise.resolve(answerText(200, body)))

    await expect(fetchResumeText(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(fetchResumeText(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    const read = watched(() => fetchResumeText(TOKEN, new AbortController().signal))

    await vi.advanceTimersByTimeAsync(4_999)
    expect(read.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(read.result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    stubFetch(answerOnlyAbort)
    const controller = new AbortController()

    const result = fetchResumeText(TOKEN, controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
  })
})

describe('saveResumeText', () => {
  it('puts the text and the upload time exactly as read, and reads back what was saved', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(answer(200, CHECKED)))

    const saved = await saveResumeText(TOKEN, TEXT, UPLOADED_AT)

    expect(saved).toEqual({
      kind: 'saved',
      resumeText: {
        uploadedAt: UPLOADED_AT,
        state: 'found',
        text: TEXT,
        checkedAt: new Date(CHECKED_AT),
      },
    })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/resume/text')
    expect(init?.method).toBe('PUT')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe(`Bearer ${TOKEN}`)
    expect(headers.get('Content-Type')).toBe('application/json')
    const sent: CheckedTextBody = { text: TEXT, uploaded_at: UPLOADED_AT }
    expect(init?.body).toBe(JSON.stringify(sent))
  })

  it('reports replaced for a 409', async () => {
    stubFetch(() => Promise.resolve(answer(409, REPLACED)))

    await expect(saveResumeText(TOKEN, TEXT, UPLOADED_AT)).resolves.toBe('replaced')
  })

  it('reports the first rule the text broke for a 422', async () => {
    stubFetch(() => Promise.resolve(answer(422, TOO_LONG)))

    await expect(saveResumeText(TOKEN, TEXT, UPLOADED_AT)).resolves.toEqual({
      kind: 'refused',
      message: 'The resume text can be at most 15,000 characters',
    })
  })

  it.each([
    ['no problems', '{"detail": []}'],
    ['a problem with no message', '{"detail": [{"type": "x", "loc": ["body"]}]}'],
    ['an empty message', '{"detail": [{"type": "x", "loc": ["body"], "msg": ""}]}'],
    ['a body that does not parse', 'Unprocessable'],
  ])('reports unavailable for a 422 with %s', async (_case, body) => {
    stubFetch(() => Promise.resolve(answerText(422, body)))

    await expect(saveResumeText(TOKEN, TEXT, UPLOADED_AT)).resolves.toBe('unavailable')
  })

  it.each(STORAGE_ANSWERS)('reports %s as %s', async (_case, outcome, reply) => {
    stubFetch(() => Promise.resolve(reply()))

    await expect(saveResumeText(TOKEN, TEXT, UPLOADED_AT)).resolves.toBe(outcome)
  })

  it('reports unavailable for a 200 holding no text, which a save never answers', async () => {
    stubFetch(() => Promise.resolve(answer(200, { ...FOUND, text: null })))

    await expect(saveResumeText(TOKEN, TEXT, UPLOADED_AT)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    const save = watched(() => saveResumeText(TOKEN, TEXT, UPLOADED_AT))

    await vi.advanceTimersByTimeAsync(4_999)
    expect(save.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(save.result).toBe('unavailable')
  })

  it('reports aborted, not saved, for an answer that lands after the caller aborts', async () => {
    const controller = new AbortController()
    stubFetch(async () => {
      controller.abort()
      return answer(200, CHECKED)
    })

    await expect(saveResumeText(TOKEN, TEXT, UPLOADED_AT, controller.signal)).resolves.toBe(
      'aborted',
    )
  })
})
