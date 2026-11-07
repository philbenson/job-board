import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchResume,
  removeResume,
  uploadResume,
  type ResumeBody,
  type StorageRefusalBody,
  type UploadedBody,
} from './resume.ts'

const TOKEN = 'header.payload.signature'
const UPLOADED_AT = '2026-11-07T20:29:59.747970Z'

const HELD = {
  resume: { size_bytes: 2064, uploaded_at: UPLOADED_AT },
} satisfies ResumeBody
const NONE = { resume: null } satisfies ResumeBody
// What an upload answers, typed by the upload's own answer.
const RECORDED = {
  resume: { size_bytes: 2064, uploaded_at: UPLOADED_AT },
} satisfies UploadedBody
const RECORDED_NONE = { resume: null } satisfies UploadedBody
const NOT_SET_UP = {
  detail: 'Resume storage is not set up',
} satisfies StorageRefusalBody
const DID_NOT_ANSWER = {
  detail: 'Resume storage did not answer; try again later',
} satisfies StorageRefusalBody

const A_PDF = new Blob(['%PDF-1.7\n%%EOF\n'], { type: 'application/pdf' })

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: ResumeBody | UploadedBody | StorageRefusalBody): Response {
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

// The answers every route gives alike when storage is the reason it cannot.
const STORAGE_ANSWERS = [
  ['a 503 saying storage is not set up', 'not set up', () => answer(503, NOT_SET_UP)],
  ['a 503 saying storage did not answer', 'storage down', () => answer(503, DID_NOT_ANSWER)],
  ['a 503 saying something else', 'unavailable', () => answerText(503, '{"detail": "down"}')],
  ['a 503 that does not parse', 'unavailable', () => answerText(503, 'Service Unavailable')],
  ['a 401', 'unavailable', () => answerText(401, '{"detail": "sign-in required"}')],
  ['a 500', 'unavailable', () => answerText(500, 'Internal Server Error')],
] as const

describe('fetchResume', () => {
  it('reads the resume from a 200, sending the token as a bearer token', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return answer(200, HELD)
    })

    await expect(fetchResume(TOKEN)).resolves.toEqual({
      kind: 'loaded',
      resume: { sizeBytes: 2064, uploadedAt: new Date(UPLOADED_AT) },
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/resume', expect.anything())
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${TOKEN}`)
  })

  it('reads no resume from a 200 with none', async () => {
    stubFetch(async () => answer(200, NONE))

    await expect(fetchResume(TOKEN)).resolves.toEqual({ kind: 'loaded', resume: null })
  })

  it.each(STORAGE_ANSWERS)('reports %s as %s', async (_case, outcome, reply) => {
    stubFetch(async () => reply())

    await expect(fetchResume(TOKEN)).resolves.toBe(outcome)
  })

  it.each([
    ['a success code other than 200', () => answer(203, HELD)],
    ['a 200 without the resume', () => answerText(200, '{}')],
    ['a 200 whose resume is not an object', () => answerText(200, '{"resume": 7}')],
    [
      'a 200 whose size is not a number',
      () => answerText(200, `{"resume": {"size_bytes": "2064", "uploaded_at": "${UPLOADED_AT}"}}`),
    ],
    [
      'a 200 whose time is not text',
      () => answerText(200, '{"resume": {"size_bytes": 2064, "uploaded_at": 7}}'),
    ],
    [
      'a 200 whose time is not a time',
      () => answerText(200, '{"resume": {"size_bytes": 2064, "uploaded_at": "yesterday"}}'),
    ],
    ['a body that does not parse', () => answerText(200, 'resume')],
    ['a body that is not an object', () => answerText(200, 'null')],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(fetchResume(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(fetchResume(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    const read = watched(() => fetchResume(TOKEN, new AbortController().signal))

    await vi.advanceTimersByTimeAsync(4_999)
    expect(read.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(read.result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    stubFetch(answerOnlyAbort)
    const controller = new AbortController()

    const result = fetchResume(TOKEN, controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
  })
})

describe('uploadResume', () => {
  it('puts the file itself as a PDF with the bearer token and reads back the resume', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return answer(200, RECORDED)
    })

    await expect(uploadResume(TOKEN, A_PDF)).resolves.toEqual({
      kind: 'loaded',
      resume: { sizeBytes: 2064, uploadedAt: new Date(UPLOADED_AT) },
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/resume', expect.anything())
    expect(init?.method).toBe('PUT')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe(`Bearer ${TOKEN}`)
    expect(headers.get('Content-Type')).toBe('application/pdf')
    expect(init?.body).toBe(A_PDF)
  })

  it.each(STORAGE_ANSWERS)('reports %s as %s', async (_case, outcome, reply) => {
    stubFetch(async () => reply())

    await expect(uploadResume(TOKEN, A_PDF)).resolves.toBe(outcome)
  })

  it.each([
    ['a 200 with no resume', () => answer(200, RECORDED_NONE)],
    ['a 413', () => answerText(413, '{"detail": "A resume can be at most 5 MB"}')],
    ['a 415', () => answerText(415, '{"detail": "That file is not a PDF"}')],
    ['a 200 that does not parse', () => answerText(200, 'stored')],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(uploadResume(TOKEN, A_PDF)).resolves.toBe('unavailable')
  })

  it('waits for a slow line and the reading of its text before it gives up', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    const upload = watched(() => uploadResume(TOKEN, A_PDF))

    await vi.advanceTimersByTimeAsync(134_999)
    expect(upload.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(upload.result).toBe('unavailable')
  })

  it('reports aborted, not loaded, for an answer that lands after the caller aborts', async () => {
    const controller = new AbortController()
    stubFetch(async () => {
      controller.abort()
      return answer(200, RECORDED)
    })

    await expect(uploadResume(TOKEN, A_PDF, controller.signal)).resolves.toBe('aborted')
  })
})

describe('removeResume', () => {
  it('deletes with the bearer token and reports removed for a 204', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return new Response(null, { status: 204 })
    })

    await expect(removeResume(TOKEN)).resolves.toBe('removed')
    expect(fetchMock).toHaveBeenCalledWith('/api/resume', expect.anything())
    expect(init?.method).toBe('DELETE')
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${TOKEN}`)
  })

  it.each(STORAGE_ANSWERS)('reports %s as %s', async (_case, outcome, reply) => {
    stubFetch(async () => reply())

    await expect(removeResume(TOKEN)).resolves.toBe(outcome)
  })

  it('reports unavailable for a 200, which is not what a removal answers', async () => {
    stubFetch(async () => answer(200, NONE))

    await expect(removeResume(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after a minute and reports unavailable', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    const removal = watched(() => removeResume(TOKEN))

    await vi.advanceTimersByTimeAsync(59_999)
    expect(removal.result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(removal.result).toBe('unavailable')
  })
})
