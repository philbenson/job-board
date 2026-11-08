import { askWithin } from './askWithin.ts'
import type { paths } from './schema.ts'

type InterviewRoute = paths['/interview']
type AnswerOperation = paths['/interview/answer']['post']

/** The signed-in person's interview, as the backend's OpenAPI description defines it. */
export type InterviewBody =
  InterviewRoute['get']['responses'][200]['content']['application/json']

/** One line of the conversation, or a section the interviewer saved. */
export type Entry = InterviewBody['entries'][number]

export type InterviewStatus = InterviewBody['status']

/** What a start still needs. */
export type MissingItem = InterviewBody['missing'][number]

/** Why the interviewer's last turn failed, as the backend names it. */
export type FailureCode = NonNullable<InterviewBody['failure']>

/** A profile section the interviewer can save. */
export type SavedSection = Extract<Entry, { kind: 'saved' }>['section']

/** The body that answers the question the interview waits on. */
export type AnswerBody = AnswerOperation['requestBody']['content']['application/json']

/** The backend's refusal of a step the interview is not in a state to take. */
export type ConflictBody =
  InterviewRoute['post']['responses'][409]['content']['application/json']

/** The backend's refusal of an answer that breaks one of its rules. */
export type AnswerRefusalBody = AnswerOperation['responses'][422]['content']['application/json']

/** The interview as the backend answered it. */
export type Got = { kind: 'interview'; interview: InterviewBody }

/** The backend's 409: the interview is not in a state for this, with its sentence. */
export type Conflict = { kind: 'conflict'; message: string }

/** The backend refused the answer, with the first rule it broke. */
export type Refused = { kind: 'refused'; message: string }

/** The backend's 404: the person has no interview to answer, retry or delete. */
export type NoInterview = 'no interview'

type Failure = 'unavailable' | 'aborted'

export type InterviewRead = Got | Failure
export type InterviewStart = Got | Conflict | Failure
export type InterviewAnswer = Got | Conflict | Refused | NoInterview | Failure
export type InterviewRetry = Got | Conflict | NoInterview | Failure
export type InterviewRemoval = 'deleted' | Conflict | NoInterview | Failure

// Every route reads or writes one row and starts at most a task, never
// waiting on the model, so a reply slower than this is no reply at all.
export const INTERVIEW_TIMEOUT_MS = 5_000

// The values the backend sends for each closed set, keyed by the generated
// union, so a value the backend adds fails the type check until it is here.
const STATUSES: Record<InterviewStatus, true> = {
  'not-started': true,
  running: true,
  waiting: true,
  failed: true,
  finished: true,
  stopped: true,
}

const MISSING: Record<MissingItem, true> = {
  'working-key': true,
  'checked-resume-text': true,
}

const FAILURES: Record<FailureCode, true> = {
  'timed-out': true,
  'connection-error': true,
  rejected: true,
  'not-permitted': true,
  'model-not-found': true,
  'no-credit': true,
  'rate-limited': true,
  'server-error': true,
  refused: true,
  'cut-off': true,
  declined: true,
  'empty-reply': true,
  'not-sealed-here': true,
  unopenable: true,
  interrupted: true,
  unexpected: true,
}

const SECTIONS: Record<SavedSection, true> = {
  target_titles: true,
  title_range: true,
  places: true,
  pay: true,
  skills: true,
  gaps: true,
  deal_breakers: true,
  companies: true,
  pace: true,
  own_rules: true,
}

/** Every failure code the backend sends, for a check that each has its sentence. */
export const FAILURE_CODES = Object.keys(FAILURES) as FailureCode[]

/** Every section the interviewer can save, for a check that each has its heading. */
export const SAVED_SECTIONS = Object.keys(SECTIONS) as SavedSection[]

const SPOKEN: Record<Exclude<Entry['kind'], 'saved'>, true> = {
  interviewer: true,
  person: true,
  notice: true,
}

/**
 * Reads the signed-in person's interview: "not-started" before any start,
 * never a 404. Resolves to it only for a 200 of the contract's shape; to
 * "unavailable" for any other answer, a failed request or no answer within
 * INTERVIEW_TIMEOUT_MS; and to "aborted" for the caller's abort. Never
 * rejects.
 */
export function fetchInterview(token: string, signal?: AbortSignal): Promise<InterviewRead> {
  return ask(signal, async (requestSignal) => {
    const response = await send('GET', '/api/interview', token, requestSignal)
    return response.status === 200 ? gotFrom(response) : 'unavailable'
  })
}

/**
 * Starts the interview, whose first turn then runs on the service. Resolves
 * to the running interview for a 202; to the backend's sentence for a 409,
 * when it has already started or a start still needs something; and like
 * fetchInterview otherwise. Never rejects.
 */
export function startInterview(token: string, signal?: AbortSignal): Promise<InterviewStart> {
  return ask(signal, async (requestSignal) => {
    const response = await send('POST', '/api/interview', token, requestSignal)
    if (response.status === 409) {
      return conflictFrom(response)
    }
    return response.status === 202 ? gotFrom(response) : 'unavailable'
  })
}

/**
 * Sends `text` as the answer to the question the interview waits on. Resolves
 * to the running interview for a 202, holding the entries from before the
 * answer; to "no interview" for a 404; to the backend's sentence for a 409;
 * to the first rule the answer broke for a 422; and like fetchInterview
 * otherwise. Never rejects.
 */
export function answerInterview(
  token: string,
  text: string,
  signal?: AbortSignal,
): Promise<InterviewAnswer> {
  const body: AnswerBody = { text }
  return ask(signal, async (requestSignal) => {
    const response = await send('POST', '/api/interview/answer', token, requestSignal, body)
    if (response.status === 422) {
      return refusedFrom(await response.json())
    }
    return stepFrom(response, 202, gotFrom)
  })
}

/**
 * Runs a failed interview's turn again. Resolves to the running interview for
 * a 202; to "no interview" for a 404; to the backend's sentence for a 409;
 * and like fetchInterview otherwise. Never rejects.
 */
export function retryInterview(token: string, signal?: AbortSignal): Promise<InterviewRetry> {
  return ask(signal, async (requestSignal) => {
    const response = await send('POST', '/api/interview/retry', token, requestSignal)
    return stepFrom(response, 202, gotFrom)
  })
}

/**
 * Deletes the conversation and every step the interviewer saved of it; the
 * profile keeps what the interview saved into it. Resolves to "deleted" for a
 * 204; to "no interview" for a 404; to the backend's sentence for a 409,
 * while a turn holds it; and like fetchInterview otherwise. Never rejects.
 */
export function deleteInterview(token: string, signal?: AbortSignal): Promise<InterviewRemoval> {
  return ask(signal, async (requestSignal) => {
    const response = await send('DELETE', '/api/interview', token, requestSignal)
    return stepFrom(response, 204, async () => 'deleted' as const)
  })
}

// Every route under one time limit, and a failed request as no answer.
function ask<T>(
  signal: AbortSignal | undefined,
  exchange: (signal: AbortSignal) => Promise<T | 'unavailable'>,
): Promise<T | Failure> {
  return askWithin(INTERVIEW_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      return await exchange(requestSignal)
    } catch {
      return 'unavailable'
    }
  })
}

function send(
  method: 'GET' | 'POST' | 'DELETE',
  url: string,
  token: string,
  signal: AbortSignal,
  body?: AnswerBody,
): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  return fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
}

// The answers the answer, retry and delete routes give alike.
async function stepFrom<T>(
  response: Response,
  success: number,
  from: (response: Response) => Promise<T | 'unavailable'>,
): Promise<T | Conflict | NoInterview | 'unavailable'> {
  if (response.status === 404) {
    return 'no interview'
  }
  if (response.status === 409) {
    return conflictFrom(response)
  }
  return response.status === success ? from(response) : 'unavailable'
}

async function gotFrom(response: Response): Promise<Got | 'unavailable'> {
  const body: unknown = await response.json()
  return isInterview(body) ? { kind: 'interview', interview: body } : 'unavailable'
}

async function conflictFrom(response: Response): Promise<Conflict | 'unavailable'> {
  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  const { detail } = body as Partial<Record<keyof ConflictBody, unknown>>
  return typeof detail === 'string' && detail !== ''
    ? { kind: 'conflict', message: detail }
    : 'unavailable'
}

function refusedFrom(body: unknown): Refused | 'unavailable' {
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  const { detail } = body as Partial<Record<keyof AnswerRefusalBody, unknown>>
  const first: unknown = Array.isArray(detail) ? detail[0] : undefined
  if (typeof first !== 'object' || first === null) {
    return 'unavailable'
  }
  type Problem = AnswerRefusalBody['detail'][number]
  const { msg } = first as Partial<Record<keyof Problem, unknown>>
  return typeof msg === 'string' && msg !== '' ? { kind: 'refused', message: msg } : 'unavailable'
}

// One of the record's own keys, never one every object inherits.
function isOneOf<T extends string>(choices: Record<T, true>, value: unknown): value is T {
  return typeof value === 'string' && Object.hasOwn(choices, value)
}

/**
 * Whether the body has the interview's shape. A status, failure code or
 * section this page does not know means it is older than the backend, and
 * only a reload brings the newer, so the body reads as no answer.
 */
function isInterview(body: unknown): body is InterviewBody {
  if (typeof body !== 'object' || body === null) {
    return false
  }
  const {
    status,
    missing,
    failure,
    question,
    entries,
    model_calls: calls,
    model_call_limit: limit,
  } = body as Partial<Record<keyof InterviewBody, unknown>>
  return (
    isOneOf(STATUSES, status) &&
    Array.isArray(missing) &&
    missing.every((item) => isOneOf(MISSING, item)) &&
    (failure === null || isOneOf(FAILURES, failure)) &&
    (question === null || typeof question === 'string') &&
    Array.isArray(entries) &&
    entries.every(isEntry) &&
    Number.isInteger(calls) &&
    Number.isInteger(limit)
  )
}

function isEntry(entry: unknown): entry is Entry {
  if (typeof entry !== 'object' || entry === null) {
    return false
  }
  type Field = keyof Extract<Entry, { kind: 'saved' }> | keyof Extract<Entry, { kind: 'person' }>
  const { kind, text, section } = entry as Partial<Record<Field, unknown>>
  return kind === 'saved' ? isOneOf(SECTIONS, section) : isOneOf(SPOKEN, kind) && typeof text === 'string'
}
