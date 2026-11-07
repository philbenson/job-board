import { askWithin } from './askWithin.ts'
import { storageRefusal, type NotSetUp, type StorageDown } from './resume.ts'
import type { paths } from './schema.ts'

type ReadOperation = paths['/resume/text']['get']
type SaveOperation = paths['/resume/text']['put']

/** What reading the resume's text gave, as the backend's OpenAPI description defines it. */
export type ResumeTextBody = ReadOperation['responses'][200]['content']['application/json']

/** The body that saves the person's checked text. */
export type CheckedTextBody = SaveOperation['requestBody']['content']['application/json']

/** The backend's refusal of text that breaks one of its rules. */
export type TextRefusalBody = SaveOperation['responses'][422]['content']['application/json']

/** How reading the file's text went; null for a resume uploaded before the reading. */
export type ReadState = ResumeTextBody['state']

/**
 * The resume's text and the person's check of it. The upload time stays the
 * exact string the backend sent: a save names the upload by it, and a Date
 * would drop its microseconds.
 */
export type ResumeText = {
  uploadedAt: string
  state: ReadState
  text: string | null
  checkedAt: Date | null
}

/** The backend refused the text, with the first rule it broke, quoting none of it. */
export type TextRefused = { kind: 'refused'; message: string }

/** The person has no resume, so there is no text to read or save. */
export type NoResume = 'no resume'

/** A newer file replaced the one this text was read from. */
export type Replaced = 'replaced'

type Failure = NoResume | NotSetUp | StorageDown | 'unavailable' | 'aborted'

export type TextRead = { kind: 'loaded'; resumeText: ResumeText } | Failure
export type TextSave = { kind: 'saved'; resumeText: ResumeText } | TextRefused | Replaced | Failure

// Both routes read or write one row, as the profile's do.
export const RESUME_TEXT_TIMEOUT_MS = 5_000

const STATES: readonly ReadState[] = ['found', 'cut', 'none_found', 'failed', null]

/**
 * Reads the text the upload read from the signed-in person's resume, and
 * their check of it. Resolves to it only for a 200 of the contract's shape;
 * to "no resume" for a 404; to "not set up" or "storage down" for the
 * service's two storage answers; to "unavailable" for any other answer, a
 * failed request or no answer within RESUME_TEXT_TIMEOUT_MS; and to "aborted"
 * for the caller's abort. Never rejects.
 */
export function fetchResumeText(token: string, signal?: AbortSignal): Promise<TextRead> {
  return askWithin(RESUME_TEXT_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/resume/text', {
        headers: { Authorization: `Bearer ${token}` },
        signal: requestSignal,
      })
      const refused = await refusalOf(response)
      if (refused !== null) {
        return refused
      }
      const resumeText = await resumeTextFrom(response)
      return resumeText === 'unavailable' ? resumeText : { kind: 'loaded', resumeText }
    } catch {
      return 'unavailable'
    }
  })
}

/**
 * Saves `text` as the person's checked text for the upload made at
 * `uploadedAt`, the string fetchResumeText gave. Resolves to the text as the
 * backend kept it for a 200; to "replaced" for a 409, when a newer file came
 * since; to the first rule the text broke for a 422; and like fetchResumeText
 * otherwise. Never rejects.
 */
export function saveResumeText(
  token: string,
  text: string,
  uploadedAt: string,
  signal?: AbortSignal,
): Promise<TextSave> {
  const body: CheckedTextBody = { text, uploaded_at: uploadedAt }
  return askWithin(RESUME_TEXT_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/resume/text', {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: requestSignal,
      })
      if (response.status === 409) {
        return 'replaced'
      }
      if (response.status === 422) {
        return refusedFrom(await response.json())
      }
      const refused = await refusalOf(response)
      if (refused !== null) {
        return refused
      }
      const resumeText = await resumeTextFrom(response)
      // A save always leaves text behind.
      return resumeText === 'unavailable' || resumeText.text === null
        ? 'unavailable'
        : { kind: 'saved', resumeText }
    } catch {
      return 'unavailable'
    }
  })
}

// The answers both routes give alike, or null for one to read further.
async function refusalOf(
  response: Response,
): Promise<NoResume | NotSetUp | StorageDown | 'unavailable' | null> {
  if (response.status === 404) {
    return 'no resume'
  }
  if (response.status === 503) {
    return storageRefusal(response)
  }
  return response.status === 200 ? null : 'unavailable'
}

async function resumeTextFrom(response: Response): Promise<ResumeText | 'unavailable'> {
  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  // Every field may be missing or of any type until checked; naming the field
  // through the body's type ties it to the backend's name for it.
  const {
    uploaded_at: uploadedAt,
    state,
    text,
    checked_at: checked,
  } = body as Partial<Record<keyof ResumeTextBody, unknown>>
  if (
    typeof uploadedAt !== 'string' ||
    Number.isNaN(new Date(uploadedAt).getTime()) ||
    !STATES.includes(state as ReadState) ||
    (text !== null && typeof text !== 'string')
  ) {
    return 'unavailable'
  }
  let checkedAt: Date | null = null
  if (checked !== null) {
    checkedAt = typeof checked === 'string' ? new Date(checked) : new Date(Number.NaN)
    if (Number.isNaN(checkedAt.getTime())) {
      return 'unavailable'
    }
  }
  return { uploadedAt, state: state as ReadState, text, checkedAt }
}

function refusedFrom(body: unknown): TextRefused | 'unavailable' {
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  const { detail } = body as Partial<Record<keyof TextRefusalBody, unknown>>
  const first: unknown = Array.isArray(detail) ? detail[0] : undefined
  if (typeof first !== 'object' || first === null) {
    return 'unavailable'
  }
  type Problem = TextRefusalBody['detail'][number]
  const { msg } = first as Partial<Record<keyof Problem, unknown>>
  return typeof msg === 'string' && msg !== '' ? { kind: 'refused', message: msg } : 'unavailable'
}
