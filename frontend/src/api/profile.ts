import { askWithin } from './askWithin.ts'
import type { paths } from './schema.ts'

type SaveOperation = paths['/profile/target-titles']['put']

/** The profile, as the backend's OpenAPI description defines it. */
export type ProfileBody =
  paths['/profile']['get']['responses'][200]['content']['application/json']

/** The body that replaces the target titles. */
export type TargetTitlesBody =
  SaveOperation['requestBody']['content']['application/json']

/** The backend's refusal of a list that breaks one of its rules. */
export type SaveRefusalBody =
  SaveOperation['responses'][422]['content']['application/json']

/** The titles the backend holds for the signed-in person. */
export type Loaded = { kind: 'loaded'; titles: string[] }

/** The titles as the backend stored them, which may differ from those sent. */
export type Saved = { kind: 'saved'; titles: string[] }

/** The backend refused the list, saying which rule it broke. */
export type Refused = { kind: 'refused'; message: string }

export type ProfileRead = Loaded | 'unavailable' | 'aborted'
export type TitlesSave = Saved | Refused | 'unavailable' | 'aborted'

// The backend checks a token without a network call and reads or writes one
// row, so a reply slower than this is treated as no reply at all.
const PROFILE_TIMEOUT_MS = 5_000

/**
 * Reads the signed-in person's target titles. Resolves to them only when the
 * service answers exactly 200 with a list of text; any other answer, a failed
 * request, or no answer within PROFILE_TIMEOUT_MS resolves to "unavailable",
 * and the caller's abort to "aborted". Never rejects.
 */
export function fetchProfile(
  token: string,
  signal?: AbortSignal,
): Promise<ProfileRead> {
  return askWithin(PROFILE_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/profile', {
        headers: { Authorization: `Bearer ${token}` },
        signal: requestSignal,
      })
      return await loadedFrom(response)
    } catch {
      return 'unavailable'
    }
  })
}

/**
 * Replaces the signed-in person's target titles with `titles`, sent whole.
 * Resolves to the titles as stored for a 200; to the backend's rule for a 422,
 * the first one it names; and like fetchProfile otherwise. Never rejects.
 */
export function saveTargetTitles(
  token: string,
  titles: string[],
  signal?: AbortSignal,
): Promise<TitlesSave> {
  const body: TargetTitlesBody = { titles }
  return askWithin(PROFILE_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/profile/target-titles', {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal: requestSignal,
      })
      if (response.status === 422) {
        return refusedFrom(await response.json())
      }
      const loaded = await loadedFrom(response)
      return loaded === 'unavailable'
        ? loaded
        : { kind: 'saved', titles: loaded.titles }
    } catch {
      return 'unavailable'
    }
  })
}

async function loadedFrom(response: Response): Promise<Loaded | 'unavailable'> {
  if (response.status !== 200) {
    return 'unavailable'
  }
  const body: unknown = await response.json()
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  // Every field may be missing or of any type until checked; naming the field
  // through the body's type ties it to the backend's name for it.
  const { target_titles: titles } = body as Partial<
    Record<keyof ProfileBody, unknown>
  >
  return isTextList(titles) ? { kind: 'loaded', titles } : 'unavailable'
}

function refusedFrom(body: unknown): Refused | 'unavailable' {
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  const { detail } = body as Partial<Record<keyof SaveRefusalBody, unknown>>
  const first: unknown = Array.isArray(detail) ? detail[0] : undefined
  if (typeof first !== 'object' || first === null) {
    return 'unavailable'
  }
  type Entry = NonNullable<SaveRefusalBody['detail']>[number]
  const { msg } = first as Partial<Record<keyof Entry, unknown>>
  return typeof msg === 'string' && msg !== ''
    ? { kind: 'refused', message: msg }
    : 'unavailable'
}

function isTextList(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === 'string')
  )
}
