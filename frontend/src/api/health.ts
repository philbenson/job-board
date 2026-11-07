export type ServiceHealth = 'ok' | 'unavailable'

/**
 * Asks the backend whether it is up. Resolves to "ok" only when the service
 * answers 200 with a status of "ok"; any other answer, a body that is not the
 * expected JSON, or a failed request resolves to "unavailable", so a caller
 * never shows the service as up without the service saying so. Never rejects.
 */
export async function fetchHealth(
  signal?: AbortSignal,
): Promise<ServiceHealth> {
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
