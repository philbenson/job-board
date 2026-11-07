import type { paths } from './schema.ts'

type ModelKeyRoute = paths['/model-key']

/** A saved key as the backend shows it: provider, last four characters, check time. */
export type SavedModelKeyBody =
  ModelKeyRoute['get']['responses'][200]['content']['application/json']

/** The answer to a read when nothing is saved. */
export type NoModelKeyBody =
  ModelKeyRoute['get']['responses'][404]['content']['application/json']

/** What a save sends: the provider and the key itself. */
export type ModelKeyToSaveBody =
  ModelKeyRoute['put']['requestBody']['content']['application/json']

/** A save the backend refused, with a sentence to show the person. */
export type ModelKeyRefusedBody =
  ModelKeyRoute['put']['responses'][422]['content']['application/json']

export type ModelKeyRead = { saved: SavedModelKeyBody } | 'none' | 'unavailable'

export type ModelKeySave =
  | { saved: SavedModelKeyBody }
  | { refused: string }
  | 'unavailable'

export type ModelKeyRemoval = 'removed' | 'unavailable'

const MODEL_KEY_URL = '/api/model-key'

/**
 * The signed-in person's saved key: "none" for the backend's 404, and
 * "unavailable" for any other answer, a body outside the contract, or a
 * failed request. Never rejects; the caller sets the time limit.
 */
export async function readModelKey(
  token: string,
  signal: AbortSignal,
): Promise<ModelKeyRead> {
  try {
    const response = await fetch(MODEL_KEY_URL, {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    })
    if (response.status === 404) {
      return 'none'
    }
    if (response.status !== 200) {
      return 'unavailable'
    }
    const body: unknown = await response.json()
    return isSavedKey(body) ? { saved: body } : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

/**
 * Sends a key to be checked and saved. The backend's 422 and 503 refusals
 * come back with their sentence; any other answer, a body outside the
 * contract, or a failed request is "unavailable". The key goes only into this
 * request's body. Never rejects; the caller sets the time limit.
 */
export async function saveModelKey(
  token: string,
  key: string,
  signal: AbortSignal,
): Promise<ModelKeySave> {
  const toSave = { provider: 'anthropic', key } satisfies ModelKeyToSaveBody
  try {
    const response = await fetch(MODEL_KEY_URL, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(toSave),
      signal,
    })
    const body: unknown = await response.json()
    if (response.status === 200) {
      return isSavedKey(body) ? { saved: body } : 'unavailable'
    }
    if (response.status === 422 || response.status === 503) {
      // A 422 for a body the backend could not read at all is a list of
      // problems, not a refusal with a sentence, and reads as no answer.
      return isRefusal(body) ? { refused: body.detail } : 'unavailable'
    }
    return 'unavailable'
  } catch {
    return 'unavailable'
  }
}

/**
 * Removes the signed-in person's key; "removed" also when none was saved.
 * Never rejects; the caller sets the time limit.
 */
export async function removeModelKey(
  token: string,
  signal: AbortSignal,
): Promise<ModelKeyRemoval> {
  try {
    const response = await fetch(MODEL_KEY_URL, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
      signal,
    })
    return response.status === 204 ? 'removed' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

// Every field may be missing or of any type until checked; naming the fields
// through the body's type ties them to the backend's names.
function fieldsOf<T>(body: unknown): Partial<Record<keyof T, unknown>> | null {
  return typeof body === 'object' && body !== null && !Array.isArray(body)
    ? (body as Partial<Record<keyof T, unknown>>)
    : null
}

function isSavedKey(body: unknown): body is SavedModelKeyBody {
  const fields = fieldsOf<SavedModelKeyBody>(body)
  return (
    fields !== null &&
    fields.provider === 'anthropic' &&
    typeof fields.last_four === 'string' &&
    typeof fields.checked_at === 'string' &&
    !Number.isNaN(Date.parse(fields.checked_at))
  )
}

function isRefusal(body: unknown): body is ModelKeyRefusedBody {
  const fields = fieldsOf<ModelKeyRefusedBody>(body)
  return fields !== null && typeof fields.detail === 'string'
}
