import { askWithin } from './askWithin.ts'
import type { paths } from './schema.ts'

/** The health route's body, as the backend's OpenAPI description defines it. */
export type HealthBody =
  paths['/health']['get']['responses'][200]['content']['application/json']

/**
 * The client's verdict: "ok" only when the service said so, "unavailable" for
 * anything it could not confirm. Its own type rather than the body's status,
 * since the client reports nothing finer than that.
 */
export type ServiceHealth = 'ok' | 'unavailable'

// Checked against the body, so renaming the value in the backend fails the
// type check here instead of showing a healthy service as unavailable.
const OK_STATUS = 'ok' satisfies HealthBody['status']

/** The caller aborted the check, so nobody wants its answer. */
export type HealthCheck = ServiceHealth | 'aborted'

// The service answers its health route within two seconds; a reply slower
// than this is treated as no reply at all.
const HEALTH_TIMEOUT_MS = 5_000

/**
 * Asks the backend whether it is up. Resolves to "ok" only when the service
 * answers exactly 200 with a status of "ok"; any other answer, a body that is
 * not the expected JSON, a failed request, or no answer within
 * HEALTH_TIMEOUT_MS resolves to "unavailable", so a caller never shows the
 * service as up without the service saying so. Resolves to "aborted" once the
 * caller's signal has aborted, and never otherwise. Never rejects.
 */
export function fetchHealth(signal?: AbortSignal): Promise<HealthCheck> {
  return askWithin(HEALTH_TIMEOUT_MS, signal, askService)
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
  if (typeof body !== 'object' || body === null) {
    return false
  }
  // Every field may be missing or of any type until checked; naming the field
  // through the body's type ties it to the backend's name for it.
  const { status } = body as Partial<Record<keyof HealthBody, unknown>>
  return status === OK_STATUS
}
