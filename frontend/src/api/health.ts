export type ServiceHealth = 'ok' | 'unavailable'

/** The caller aborted the check, so nobody wants its answer. */
export type HealthCheck = ServiceHealth | 'aborted'

// The service answers its health route within two seconds; a reply slower
// than this is treated as no reply at all.
export const HEALTH_TIMEOUT_MS = 5_000

/**
 * Asks the backend whether it is up. Resolves to "ok" only when the service
 * answers exactly 200 with a status of "ok"; any other answer, a body that is
 * not the expected JSON, a failed request, or no answer within
 * HEALTH_TIMEOUT_MS resolves to "unavailable", so a caller never shows the
 * service as up without the service saying so. Resolves to "aborted" once the
 * caller's signal has aborted, and never otherwise. Never rejects.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthCheck> {
  // Its own controller, so a timeout aborts the request without making the
  // caller's signal read as aborted.
  const timeout = new AbortController()
  const timer = setTimeout(() => {
    timeout.abort()
  }, HEALTH_TIMEOUT_MS)
  const requestSignal =
    signal === undefined
      ? timeout.signal
      : AbortSignal.any([signal, timeout.signal])

  const health = await askService(requestSignal)
  clearTimeout(timer)
  return signal?.aborted ? 'aborted' : health
}

async function askService(signal: AbortSignal): Promise<ServiceHealth> {
  try {
    const response = await fetch('/api/health', { signal })
    if (response.status !== 200) {
      return 'unavailable'
    }
    const body: unknown = await response.json()
    return isOkBody(body) ? 'ok' : 'unavailable'
  } catch {
    return 'unavailable'
  }
}

function isOkBody(body: unknown): boolean {
  return (
    typeof body === 'object' &&
    body !== null &&
    'status' in body &&
    body.status === 'ok'
  )
}
