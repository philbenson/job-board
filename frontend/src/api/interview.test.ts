import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  answerInterview,
  deleteInterview,
  fetchInterview,
  retryInterview,
  startInterview,
  type AnswerBody,
  type AnswerRefusalBody,
  type ConflictBody,
  type InterviewBody,
} from './interview.ts'

const TOKEN = 'header.payload.signature'

const WAITING = {
  status: 'waiting',
  missing: [],
  failure: null,
  question: 'Which titles are you after?',
  entries: [
    { kind: 'notice', text: 'The interviewer has read your resume.' },
    { kind: 'saved', section: 'skills' },
    { kind: 'interviewer', text: 'Which titles are you after?' },
  ],
  model_calls: 3,
  model_call_limit: 60,
} satisfies InterviewBody
const RUNNING = { ...WAITING, status: 'running', question: null } satisfies InterviewBody
const NOT_WAITING = { detail: 'The interview is not waiting on an answer' } satisfies ConflictBody
const NO_INTERVIEW = { detail: 'No interview started' } satisfies ConflictBody
const BLANK = {
  detail: [{ type: 'answer_blank', loc: ['body', 'text'], msg: 'An answer cannot be blank' }],
} satisfies AnswerRefusalBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: InterviewBody | ConflictBody | AnswerRefusalBody): Promise<Response> {
  return Promise.resolve(answerText(status, JSON.stringify(body)))
}

// A body outside the contract, written out on purpose.
function answerText(status: number, text: string): Response {
  return new Response(text, { status, headers: { 'Content-Type': 'application/json' } })
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

describe('fetchInterview', () => {
  it('reads the interview from a 200 with the bearer token', async () => {
    const fetchMock = stubFetch(() => answer(200, WAITING))

    await expect(fetchInterview(TOKEN)).resolves.toEqual({ kind: 'interview', interview: WAITING })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/interview')
    expect(init?.method).toBe('GET')
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${TOKEN}`)
  })

  it.each([
    ['a status it does not know', { ...WAITING, status: 'paused' }],
    ['a failure code it does not know', { ...WAITING, failure: 'lost-claim' }],
    ['no failure code, not even null', { ...WAITING, failure: undefined }],
    ['a missing item it does not know', { ...WAITING, missing: ['payment'] }],
    ['a missing item named after a property every object inherits', { ...WAITING, missing: ['constructor'] }],
    ['a question that is not text', { ...WAITING, question: 7 }],
    ['no question, not even null', { ...WAITING, question: undefined }],
    ['an entry of a kind it does not know', { ...WAITING, entries: [{ kind: 'aside', text: 'Hi' }] }],
    ['a line without its text', { ...WAITING, entries: [{ kind: 'interviewer' }] }],
    ['a saved section it does not know', { ...WAITING, entries: [{ kind: 'saved', section: 'hobbies' }] }],
    ['a count that is not a whole number', { ...WAITING, model_calls: 2.5 }],
    ['no limit', { ...WAITING, model_call_limit: undefined }],
  ])('reports unavailable for a body with %s', async (_shape, body) => {
    stubFetch(() => Promise.resolve(answerText(200, JSON.stringify(body))))

    await expect(fetchInterview(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable for a 401 and for a failed request', async () => {
    stubFetch(() => answer(401, { detail: 'No valid session token' }))
    await expect(fetchInterview(TOKEN)).resolves.toBe('unavailable')

    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')))
    await expect(fetchInterview(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)

    const read = watched(() => fetchInterview(TOKEN))
    await vi.advanceTimersByTimeAsync(4_999)
    expect(read.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(read.result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    stubFetch(answerOnlyAbort)
    const controller = new AbortController()

    const read = fetchInterview(TOKEN, controller.signal)
    controller.abort()
    await expect(read).resolves.toBe('aborted')
  })
})

describe('startInterview', () => {
  it('posts the start and reads the running interview from a 202', async () => {
    const fetchMock = stubFetch(() => answer(202, { ...RUNNING, entries: [] }))

    await expect(startInterview(TOKEN)).resolves.toEqual({
      kind: 'interview',
      interview: { ...RUNNING, entries: [] },
    })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/interview')
    expect(init?.method).toBe('POST')
  })

  it("reports a 409's sentence", async () => {
    stubFetch(() => answer(409, { detail: 'Your interview has already started' }))

    await expect(startInterview(TOKEN)).resolves.toEqual({
      kind: 'conflict',
      message: 'Your interview has already started',
    })
  })

  it('reports unavailable for a 409 without a sentence, and for a 200', async () => {
    stubFetch(() => Promise.resolve(answerText(409, '{"detail": ""}')))
    await expect(startInterview(TOKEN)).resolves.toBe('unavailable')

    stubFetch(() => answer(200, RUNNING))
    await expect(startInterview(TOKEN)).resolves.toBe('unavailable')
  })
})

describe('answerInterview', () => {
  it('posts the answer as typed, line breaks and all, and reads the 202', async () => {
    const fetchMock = stubFetch(() => answer(202, RUNNING))
    const text = 'Staff engineer\n\tor principal'

    await expect(answerInterview(TOKEN, text)).resolves.toEqual({ kind: 'interview', interview: RUNNING })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/interview/answer')
    expect(init?.method).toBe('POST')
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(init?.body as string)).toEqual({ text } satisfies AnswerBody)
  })

  it("reports a 404 as no interview, a 409's sentence and a 422's first rule", async () => {
    stubFetch(() => answer(404, NO_INTERVIEW))
    await expect(answerInterview(TOKEN, 'Hi')).resolves.toBe('no interview')

    stubFetch(() => answer(409, NOT_WAITING))
    await expect(answerInterview(TOKEN, 'Hi')).resolves.toEqual({
      kind: 'conflict',
      message: NOT_WAITING.detail,
    })

    stubFetch(() => answer(422, BLANK))
    await expect(answerInterview(TOKEN, ' ')).resolves.toEqual({
      kind: 'refused',
      message: 'An answer cannot be blank',
    })
  })

  it('reports unavailable for a 422 naming no rule', async () => {
    stubFetch(() => Promise.resolve(answerText(422, '{"detail": []}')))

    await expect(answerInterview(TOKEN, 'Hi')).resolves.toBe('unavailable')
  })

  it('gives up after five seconds', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)

    const sent = watched(() => answerInterview(TOKEN, 'Hi'))
    await vi.advanceTimersByTimeAsync(4_999)
    expect(sent.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(sent.result).toBe('unavailable')
  })
})

describe('retryInterview', () => {
  it('posts the retry and reads the 202, a 404 and a 409', async () => {
    const fetchMock = stubFetch(() => answer(202, RUNNING))
    await expect(retryInterview(TOKEN)).resolves.toEqual({ kind: 'interview', interview: RUNNING })
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/interview/retry')
    expect(init?.method).toBe('POST')

    stubFetch(() => answer(404, NO_INTERVIEW))
    await expect(retryInterview(TOKEN)).resolves.toBe('no interview')

    const notFailed = { detail: 'The interview has not failed, so there is nothing to retry' }
    stubFetch(() => answer(409, notFailed))
    await expect(retryInterview(TOKEN)).resolves.toEqual({ kind: 'conflict', message: notFailed.detail })
  })

  it('gives up after five seconds', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)

    const retried = watched(() => retryInterview(TOKEN))
    await vi.advanceTimersByTimeAsync(4_999)
    expect(retried.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(retried.result).toBe('unavailable')
  })
})

describe('deleteInterview', () => {
  it('sends the delete and reads a 204, a 404 and a 409', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(new Response(null, { status: 204 })))
    await expect(deleteInterview(TOKEN)).resolves.toBe('deleted')
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/interview')
    expect(init?.method).toBe('DELETE')

    stubFetch(() => answer(404, NO_INTERVIEW))
    await expect(deleteInterview(TOKEN)).resolves.toBe('no interview')

    const running = { detail: 'The interview is taking its turn; wait for it to finish' }
    stubFetch(() => answer(409, running))
    await expect(deleteInterview(TOKEN)).resolves.toEqual({ kind: 'conflict', message: running.detail })
  })

  it('reports unavailable for a 200', async () => {
    stubFetch(() => answer(200, WAITING))

    await expect(deleteInterview(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)

    const deleted = watched(() => deleteInterview(TOKEN))
    await vi.advanceTimersByTimeAsync(4_999)
    expect(deleted.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(deleted.result).toBe('unavailable')
  })
})
