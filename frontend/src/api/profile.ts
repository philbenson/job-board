import { askWithin } from './askWithin.ts'
import type { components, paths } from './schema.ts'

type Schemas = components['schemas']

/** The profile, as the backend's OpenAPI description defines it. */
export type ProfileBody =
  paths['/profile']['get']['responses'][200]['content']['application/json']

/** The route that replaces one section, each answering the whole profile. */
export type SectionRoute = Extract<keyof paths, `/profile/${string}`>

/** The body a section's route takes. */
export type SectionBody<Route extends SectionRoute> =
  paths[Route]['put']['requestBody']['content']['application/json']

/** The body that replaces the target titles. */
export type TargetTitlesBody = SectionBody<'/profile/target-titles'>

/** The backend's refusal of a body that breaks one of its rules. */
export type SaveRefusalBody =
  paths['/profile/target-titles']['put']['responses'][422]['content']['application/json']

export type StateCode = Schemas['Places']['states'][number]
export type CompanySize = Schemas['DealBreakers']['company_sizes'][number]

/**
 * Each code the backend takes for a state, with its name. Keyed by the
 * generated codes, so a code the backend adds without a name here fails the
 * type check; the read below takes only these codes.
 */
export const STATE_NAMES: Record<StateCode, string> = {
  AK: 'Alaska',
  AL: 'Alabama',
  AR: 'Arkansas',
  AZ: 'Arizona',
  CA: 'California',
  CO: 'Colorado',
  CT: 'Connecticut',
  DC: 'District of Columbia',
  DE: 'Delaware',
  FL: 'Florida',
  GA: 'Georgia',
  HI: 'Hawaii',
  IA: 'Iowa',
  ID: 'Idaho',
  IL: 'Illinois',
  IN: 'Indiana',
  KS: 'Kansas',
  KY: 'Kentucky',
  LA: 'Louisiana',
  MA: 'Massachusetts',
  MD: 'Maryland',
  ME: 'Maine',
  MI: 'Michigan',
  MN: 'Minnesota',
  MO: 'Missouri',
  MS: 'Mississippi',
  MT: 'Montana',
  NC: 'North Carolina',
  ND: 'North Dakota',
  NE: 'Nebraska',
  NH: 'New Hampshire',
  NJ: 'New Jersey',
  NM: 'New Mexico',
  NV: 'Nevada',
  NY: 'New York',
  OH: 'Ohio',
  OK: 'Oklahoma',
  OR: 'Oregon',
  PA: 'Pennsylvania',
  RI: 'Rhode Island',
  SC: 'South Carolina',
  SD: 'South Dakota',
  TN: 'Tennessee',
  TX: 'Texas',
  UT: 'Utah',
  VA: 'Virginia',
  VT: 'Vermont',
  WA: 'Washington',
  WI: 'Wisconsin',
  WV: 'West Virginia',
  WY: 'Wyoming',
}

/** Each company size the backend takes, by number of employees, as said. */
export const COMPANY_SIZE_NAMES: Record<CompanySize, string> = {
  '1-10': '1 to 10 people',
  '11-50': '11 to 50 people',
  '51-200': '51 to 200 people',
  '201-500': '201 to 500 people',
  '501-1000': '501 to 1,000 people',
  '1001-5000': '1,001 to 5,000 people',
  '5001-10000': '5,001 to 10,000 people',
  '10001+': '10,001 or more people',
}

// Which section of the answered profile each route replaces.
const SECTION_OF = {
  '/profile/target-titles': 'target_titles',
  '/profile/title-range': 'title_range',
  '/profile/places': 'places',
  '/profile/pay': 'pay',
  '/profile/skills': 'skills',
  '/profile/gaps': 'gaps',
  '/profile/deal-breakers': 'deal_breakers',
  '/profile/companies': 'companies',
  '/profile/pace': 'pace',
  '/profile/own-rules': 'own_rules',
} as const satisfies Record<SectionRoute, keyof ProfileBody>

/** A section as the backend holds it once saved, so never null. */
export type StoredSection<Route extends SectionRoute> = NonNullable<
  ProfileBody[(typeof SECTION_OF)[Route]]
>

/** Every section the backend holds for the signed-in person. */
export type Loaded = { kind: 'loaded'; profile: ProfileBody }

/** The section as the backend stored it, which may differ from what was sent. */
export type Saved<Route extends SectionRoute> = {
  kind: 'saved'
  section: StoredSection<Route>
}

/**
 * The backend refused the body, saying which rule it broke, and where in the
 * body: the field, then an item's place in a list and a field within that
 * item, such as ["offices", 2, "city"]; empty when it names no place.
 */
export type Refused = {
  kind: 'refused'
  message: string
  at: (string | number)[]
}

export type ProfileRead = Loaded | 'unavailable' | 'aborted'
export type SectionSave<Route extends SectionRoute> =
  | Saved<Route>
  | Refused
  | 'unavailable'
  | 'aborted'

// The backend checks a token without a network call and reads or writes one
// row, so a reply slower than this is treated as no reply at all.
const PROFILE_TIMEOUT_MS = 5_000

/**
 * Reads the signed-in person's profile. Resolves to every section only when
 * the service answers exactly 200 with a profile of the described shape; any
 * other answer, a failed request, or no answer within PROFILE_TIMEOUT_MS
 * resolves to "unavailable", and the caller's abort to "aborted". Never
 * rejects.
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
      const profile = await profileFrom(response)
      return profile === null ? 'unavailable' : { kind: 'loaded', profile }
    } catch {
      return 'unavailable'
    }
  })
}

/**
 * Replaces one section of the signed-in person's profile with `body`, sent
 * whole to its route. Resolves to the section as stored for a 200; to the
 * backend's rule for a 422, the first one it names, with where in the body it
 * points; and like fetchProfile otherwise. Never rejects.
 */
export function saveSection<Route extends SectionRoute>(
  token: string,
  route: Route,
  body: SectionBody<Route>,
  signal?: AbortSignal,
): Promise<SectionSave<Route>> {
  return askWithin(PROFILE_TIMEOUT_MS, signal, async (requestSignal) => {
    try {
      const response = await fetch(`/api${route}`, {
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
      const profile = await profileFrom(response)
      // A section just saved cannot read as unanswered: the answer is not
      // what the save stored.
      const section = profile?.[SECTION_OF[route]] ?? null
      return section === null
        ? 'unavailable'
        : { kind: 'saved', section: section as StoredSection<Route> }
    } catch {
      return 'unavailable'
    }
  })
}

async function profileFrom(response: Response): Promise<ProfileBody | null> {
  if (response.status !== 200) {
    return null
  }
  const body: unknown = await response.json()
  return isProfile(body) ? body : null
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
  const { msg, loc } = first as Partial<Record<keyof Entry, unknown>>
  return typeof msg === 'string' && msg !== ''
    ? { kind: 'refused', message: msg, at: placeIn(loc) }
    : 'unavailable'
}

// A rule about the body is placed at ["body", …the place within it]; any
// other place names nothing in what was sent.
function placeIn(loc: unknown): (string | number)[] {
  if (!Array.isArray(loc) || loc[0] !== 'body') {
    return []
  }
  const within: unknown[] = loc.slice(1)
  return within.every(
    (part) => typeof part === 'string' || typeof part === 'number',
  )
    ? (within as (string | number)[])
    : []
}

// The small checks the read is built from, each answering whether a value
// has the shape its type says.
type Check<T> = (value: unknown) => value is T

const isText: Check<string> = (value) => typeof value === 'string'

const isWholeNumber: Check<number> = (value): value is number =>
  Number.isInteger(value)

const isYesOrNo: Check<boolean> = (value) => typeof value === 'boolean'

function listOf<T>(check: Check<T>): Check<T[]> {
  return (value): value is T[] => Array.isArray(value) && value.every(check)
}

function orNull<T>(check: Check<T>): Check<T | null> {
  return (value): value is T | null => value === null || check(value)
}

// One of the record's own keys, never one every object inherits.
function oneOf<T extends string>(choices: Record<T, unknown>): Check<T> {
  return (value): value is T =>
    typeof value === 'string' && Object.hasOwn(choices, value)
}

/**
 * An object with exactly these keys, each passing its check. The checks are
 * typed by the object's own keys, so a field the backend adds or drops fails
 * the type check until the read checks it too.
 */
function objectOf<T extends object>(checks: {
  [Key in keyof T]-?: Check<T[Key]>
}): Check<T> {
  const keys = Object.keys(checks)
  return (value): value is T => {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      return false
    }
    const given = Object.keys(value)
    return (
      given.length === keys.length &&
      keys.every(
        (key) =>
          Object.hasOwn(value, key) &&
          (checks as Record<string, Check<unknown>>)[key]?.(
            (value as Record<string, unknown>)[key],
          ) === true,
      )
    )
  }
}

const isProfile = objectOf<ProfileBody>({
  target_titles: listOf(isText),
  title_range: orNull(
    objectOf<Schemas['TitleRange']>({
      nearby_titles: listOf(isText),
      lower_level_ok: isYesOrNo,
    }),
  ),
  places: orNull(
    objectOf<Schemas['Places']>({
      remote_ok: isYesOrNo,
      offices: listOf(
        objectOf<Schemas['Office']>({
          city: isText,
          days_a_week: isWholeNumber,
        }),
      ),
      states: listOf(oneOf(STATE_NAMES)),
      will_relocate: isYesOrNo,
      relocate_for: listOf(isText),
    }),
  ),
  pay: orNull(
    objectOf<Schemas['Pay']>({
      floor_usd: isWholeNumber,
      ask_usd: isWholeNumber,
    }),
  ),
  skills: orNull(
    objectOf<Schemas['Skills']>({
      skills: listOf(
        objectOf<Schemas['Skill']>({ name: isText, years: isWholeNumber }),
      ),
    }),
  ),
  gaps: orNull(
    objectOf<Schemas['Gaps']>({
      apply_with: listOf(isText),
      trade_offs: listOf(isText),
    }),
  ),
  deal_breakers: orNull(
    objectOf<Schemas['DealBreakers']>({
      industries: listOf(isText),
      company_sizes: listOf(oneOf(COMPANY_SIZE_NAMES)),
      no_agencies: isYesOrNo,
    }),
  ),
  companies: orNull(
    objectOf<Schemas['Companies']>({
      watch: listOf(isText),
      applied: listOf(
        objectOf<Schemas['Application']>({ company: isText, title: isText }),
      ),
    }),
  ),
  pace: orNull(
    objectOf<Schemas['Pace']>({
      leads_per_day: isWholeNumber,
      brief_from_score: orNull(isWholeNumber),
    }),
  ),
  own_rules: orNull(
    objectOf<Schemas['OwnRules']>({ rules: listOf(isText) }),
  ),
})
