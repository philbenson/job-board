import { vi } from 'vitest'
import type { AnswerRefusalBody, ConflictBody, InterviewBody } from '../api/interview.ts'

/** The interview as the backend reads it before any start, with these overrides. */
export function interviewWith(overrides: Partial<InterviewBody> = {}): InterviewBody {
  return {
    status: 'not-started',
    missing: [],
    failure: null,
    question: null,
    entries: [],
    model_calls: 0,
    model_call_limit: 60,
    ...overrides,
  }
}

/** How one interview route answers, given what was sent. */
type InterviewReply = (init?: RequestInit) => Promise<Response>

/** A body the contract allows, typed so it changes when the backend's does. */
export function interviewAnswer(
  status: number,
  body?: InterviewBody | ConflictBody | AnswerRefusalBody,
): Promise<Response> {
  return Promise.resolve(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    }),
  )
}

/** A request that never answers, and fails the way fetch does when aborted. */
function interviewOnlyAbort(init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

/**
 * A reply that holds each answer until the test gives it; `finish` answers
 * the latest request, and `count` says how many have come.
 */
export function heldInterviewReply() {
  let finish: (response: Response) => void = () => {}
  let count = 0
  const reply: InterviewReply = () => {
    count += 1
    return new Promise<Response>((resolve) => {
      finish = resolve
    })
  }
  return {
    reply,
    finish: async (status: number, body?: InterviewBody | ConflictBody) => {
      finish(await interviewAnswer(status, body))
    },
    count: () => count,
  }
}

/** The interview's routes, each standing for one method and path. */
type InterviewRoutes = {
  read: InterviewReply
  start: InterviewReply
  answer: InterviewReply
  retry: InterviewReply
  remove: InterviewReply
}

function routeOf(url: string, method: string | undefined): keyof InterviewRoutes | null {
  if (url === '/api/interview') {
    return method === 'POST' ? 'start' : method === 'DELETE' ? 'remove' : 'read'
  }
  if (url === '/api/interview/answer' && method === 'POST') {
    return 'answer'
  }
  return url === '/api/interview/retry' && method === 'POST' ? 'retry' : null
}

/**
 * Stands in for the service's interview routes, each answering as `routes`
 * says and never answering when it says nothing. `others` answers every
 * other request, refused by default.
 */
export function stubInterviewService(
  routes: Partial<InterviewRoutes>,
  others: (url: string, init?: RequestInit) => Promise<Response> = (url) =>
    Promise.reject(new TypeError(`unexpected request to ${url}`)),
) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const route = routeOf(url, init?.method)
    if (route === null) {
      return others(url, init)
    }
    return (routes[route] ?? interviewOnlyAbort)(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The requests made to one interview route, in order. */
export function callsTo(
  fetchMock: ReturnType<typeof stubInterviewService>,
  route: keyof InterviewRoutes,
): (RequestInit | undefined)[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => routeOf(url, init?.method) === route)
    .map(([, init]) => init)
}
