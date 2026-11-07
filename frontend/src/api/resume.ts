import { askWithin } from './askWithin.ts'
import type { paths } from './schema.ts'

type ReadOperation = paths['/resume']['get']
type UploadOperation = paths['/resume']['put']

/** The resume, or null, as the backend's OpenAPI description defines it. */
export type ResumeBody =
  ReadOperation['responses'][200]['content']['application/json']

/** The resume an upload recorded, as the backend's OpenAPI description defines it. */
export type UploadedBody =
  UploadOperation['responses'][200]['content']['application/json']

/** The backend's answer when resume storage is why it cannot do what was asked. */
export type StorageRefusalBody =
  ReadOperation['responses'][503]['content']['application/json']

/** The signed-in person's resume, as the backend recorded it. */
export type Resume = { sizeBytes: number; uploadedAt: Date }

/** What the backend holds: a resume, or null before the first upload. */
export type Loaded = { kind: 'loaded'; resume: Resume | null }

/** The service runs without resume storage set up. */
export type NotSetUp = 'not set up'

/** The service has storage set up, but the store did not answer it. */
export type StorageDown = 'storage down'

export type ResumeRead = Loaded | NotSetUp | StorageDown | 'unavailable' | 'aborted'
export type ResumeUpload =
  | { kind: 'loaded'; resume: Resume }
  | NotSetUp
  | StorageDown
  | 'unavailable'
  | 'aborted'
export type ResumeRemoval = 'removed' | NotSetUp | StorageDown | 'unavailable' | 'aborted'

// Reading answers from one row, as the profile does.
export const RESUME_READ_TIMEOUT_MS = 5_000
// The service waits on the store for up to about 51 seconds: two tries, each
// up to 5 seconds to connect and 20 to answer, and a pause of at most a second
// between them (CLIENT_CONFIG in the backend's resumes/store.py).
// Up to 5 MB on a line as slow as about 600 kilobits a second, which takes the
// other 69 seconds, then the store's answer.
export const RESUME_UPLOAD_TIMEOUT_MS = 120_000
// The store's answer, with room to spare for the request and the database.
export const RESUME_REMOVE_TIMEOUT_MS = 60_000

// The backend's sentences for its two storage answers, both 503.
const NOT_SET_UP_DETAIL = 'Resume storage is not set up'
const DID_NOT_ANSWER_DETAIL = 'Resume storage did not answer; try again later'

/**
 * Reads the signed-in person's resume. Resolves to it, or to null before the
 * first upload, only when the service answers exactly 200 with the contract's
 * shape; to "not set up" or "storage down" for the service's two storage
 * answers, which every resume route gives alike; to "unavailable" for any
 * other answer, a failed request or no answer within RESUME_READ_TIMEOUT_MS;
 * and to "aborted" for the caller's abort. Never rejects.
 */
export function fetchResume(token: string, signal?: AbortSignal): Promise<ResumeRead> {
  return askWithin(RESUME_READ_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/resume', {
        headers: { Authorization: `Bearer ${token}` },
        signal: requestSignal,
      })
      if (response.status === 503) {
        return await storageRefusal(response)
      }
      return await loadedFrom<ResumeBody>(response)
    } catch {
      return 'unavailable'
    }
  })
}

/**
 * Sends `file` as the signed-in person's resume, replacing any before it. The
 * file is the request's body as it is, so the browser declares its length,
 * which the service needs. Resolves to the resume as recorded for a 200; to
 * "not set up" or "storage down" for the service's two storage answers; and
 * like fetchResume otherwise, under RESUME_UPLOAD_TIMEOUT_MS. The service's
 * own refusals of the file are "unavailable": the panel checks the size and
 * the first bytes before it sends. Never rejects.
 */
export function uploadResume(
  token: string,
  // The description gives this body as a string of binary, which is how
  // OpenAPI spells "a file"; the file goes as the body as it is, so this takes
  // the Blob a file input gives rather than that type.
  file: Blob,
  signal?: AbortSignal,
): Promise<ResumeUpload> {
  return askWithin(RESUME_UPLOAD_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/resume', {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/pdf',
        },
        body: file,
        signal: requestSignal,
      })
      if (response.status === 503) {
        return await storageRefusal(response)
      }
      const loaded = await loadedFrom<UploadedBody>(response)
      return loaded === 'unavailable' || loaded.resume === null
        ? 'unavailable'
        : { kind: 'loaded', resume: loaded.resume }
    } catch {
      return 'unavailable'
    }
  })
}

/**
 * Removes the signed-in person's resume. Resolves to "removed" for a 204,
 * which the service also answers when there was none; to "not set up" or
 * "storage down" for its two storage answers; and like fetchResume otherwise,
 * under RESUME_REMOVE_TIMEOUT_MS. Never rejects.
 */
export function removeResume(token: string, signal?: AbortSignal): Promise<ResumeRemoval> {
  return askWithin(RESUME_REMOVE_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/resume', {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
        signal: requestSignal,
      })
      if (response.status === 204) {
        return 'removed'
      }
      return response.status === 503 ? await storageRefusal(response) : 'unavailable'
    } catch {
      return 'unavailable'
    }
  })
}

async function storageRefusal(
  response: Response,
): Promise<NotSetUp | StorageDown | 'unavailable'> {
  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  const { detail } = body as Partial<Record<keyof StorageRefusalBody, unknown>>
  if (detail === NOT_SET_UP_DETAIL) {
    return 'not set up'
  }
  return detail === DID_NOT_ANSWER_DETAIL ? 'storage down' : 'unavailable'
}

// Body names the operation's own answer, so each route's fields are checked
// against its own description.
async function loadedFrom<Body extends ResumeBody | UploadedBody>(
  response: Response,
): Promise<Loaded | 'unavailable'> {
  if (response.status !== 200) {
    return 'unavailable'
  }
  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null || !('resume' in body)) {
    return 'unavailable'
  }
  // Every field may be missing or of any type until checked; naming the field
  // through the body's type ties it to the backend's name for it.
  const { resume } = body as Record<keyof Body, unknown>
  if (resume === null) {
    return { kind: 'loaded', resume: null }
  }
  if (typeof resume !== 'object') {
    return 'unavailable'
  }
  type Saved = NonNullable<Body['resume']>
  const { size_bytes: size, uploaded_at: uploaded } = resume as Partial<
    Record<keyof Saved, unknown>
  >
  if (typeof size !== 'number' || typeof uploaded !== 'string') {
    return 'unavailable'
  }
  const uploadedAt = new Date(uploaded)
  return Number.isNaN(uploadedAt.getTime())
    ? 'unavailable'
    : { kind: 'loaded', resume: { sizeBytes: size, uploadedAt } }
}
