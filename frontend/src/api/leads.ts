import { askWithin } from './askWithin.ts'
import type { paths } from './schema.ts'

/** The leads route's body, as the backend's OpenAPI description defines it. */
export type LeadsBody =
  paths['/leads']['get']['responses'][200]['content']['application/json']

/** One open posting scored for the signed-in person. */
export type Lead = LeadsBody['leads'][number]

/** The person's best leads, best first, and how many they have in all. */
export type Loaded = { kind: 'loaded'; leads: Lead[]; total: number }

export type LeadsRead = Loaded | 'unavailable' | 'aborted'

// The backend checks a token without a network call and reads one person's
// scored rows, so a reply slower than this is treated as no reply at all.
const LEADS_TIMEOUT_MS = 5_000

// The backend's scale, which it holds the score to.
const LOWEST_SCORE = 1
const HIGHEST_SCORE = 5

// One check per field, keyed by the body's own field names, so a field the
// backend adds or renames fails the type check here until it is checked.
const LEAD_FIELDS: Record<keyof Lead, (value: unknown) => boolean> = {
  posting_id: Number.isInteger,
  title: isText,
  company: isText,
  location: (value) => value === null || isText(value),
  url: isText,
  published_at: (value) => value === null || isDate(value),
  score: (value) =>
    Number.isInteger(value) &&
    (value as number) >= LOWEST_SCORE &&
    (value as number) <= HIGHEST_SCORE,
  reason: isText,
  scored_at: isDate,
}

/**
 * Reads the signed-in person's leads. Resolves to them only when the service
 * answers exactly 200 with leads of the expected shape and a total no smaller
 * than the leads it sent; any other answer, a failed request, or no answer
 * within LEADS_TIMEOUT_MS resolves to "unavailable", and the caller's abort
 * to "aborted". Never rejects.
 */
export function fetchLeads(
  token: string,
  signal?: AbortSignal,
): Promise<LeadsRead> {
  return askWithin(LEADS_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch('/api/leads', {
        headers: { Authorization: `Bearer ${token}` },
        signal: requestSignal,
      })
      if (response.status !== 200) {
        return 'unavailable'
      }
      return loadedFrom(await response.json())
    } catch {
      return 'unavailable'
    }
  })
}

function loadedFrom(body: unknown): Loaded | 'unavailable' {
  if (typeof body !== 'object' || body === null) {
    return 'unavailable'
  }
  // Every field may be missing or of any type until checked; naming the field
  // through the body's type ties it to the backend's name for it.
  const { leads, total } = body as Partial<Record<keyof LeadsBody, unknown>>
  if (!Array.isArray(leads) || !leads.every(isLead)) {
    return 'unavailable'
  }
  if (!Number.isInteger(total) || (total as number) < leads.length) {
    return 'unavailable'
  }
  return { kind: 'loaded', leads, total: total as number }
}

function isLead(value: unknown): value is Lead {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const fields = value as Partial<Record<keyof Lead, unknown>>
  return Object.entries(LEAD_FIELDS).every(([name, check]) =>
    check(fields[name as keyof Lead]),
  )
}

function isText(value: unknown): boolean {
  return typeof value === 'string'
}

// A date the page can format: text that parses as one.
function isDate(value: unknown): boolean {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}
