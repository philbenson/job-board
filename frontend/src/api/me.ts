/**
 * What the backend said of the signed-in person: it recognised them, it
 * refused their sign-in, or it gave no usable answer.
 */
export type MeAnswer = 'recognised' | 'refused' | 'unavailable'

/** The caller aborted the request, so nobody wants its answer. */
export type MeCheck = MeAnswer | 'aborted'

// The backend checks a token without a network call and reads one row, so a
// reply slower than this is treated as no reply at all.
const ME_TIMEOUT_MS = 5_000

/**
 * Asks the backend who the bearer of a session token is. Resolves to
 * "recognised" only when the service answers exactly 200 with the person's
 * whole-number id, and to "refused" only for a 401; any other answer, a body
 * that is not the expected JSON, a failed request, or no answer within
 * ME_TIMEOUT_MS resolves to "unavailable", so a caller never shows the person
 * as recognised without the service saying so. Resolves to "aborted" once the
 * caller's signal has aborted, and never otherwise. Never rejects.
 */
export async function fetchMe(
  token: string,
  signal?: AbortSignal,
): Promise<MeCheck> {
  // Its own controller, so a timeout aborts the request without making the
  // caller's signal read as aborted.
  const timeout = new AbortController()
  const timer = setTimeout(() => {
    timeout.abort()
  }, ME_TIMEOUT_MS)
  const requestSignal =
    signal === undefined
      ? timeout.signal
      : AbortSignal.any([signal, timeout.signal])

  const me = await askService(token, requestSignal)
  clearTimeout(timer)
  return signal?.aborted ? 'aborted' : me
}

async function askService(
  token: string,
  signal: AbortSignal,
): Promise<MeAnswer> {
  try {
    const response = await fetch('/api/me', {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    })
    if (response.status === 401) {
      return 'refused'
    }
    if (response.status !== 200) {
      return 'unavailable'
    }
    const body: unknown = await response.json()
    return isPersonBody(body) ? 'recognised' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

function isPersonBody(body: unknown): boolean {
  return (
    typeof body === 'object' &&
    body !== null &&
    'id' in body &&
    Number.isInteger(body.id)
  )
}
