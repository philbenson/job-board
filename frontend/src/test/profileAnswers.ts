import { vi } from 'vitest'
import type {
  ProfileBody,
  SaveRefusalBody,
  SectionRoute,
} from '../api/profile.ts'

/**
 * The profile the backend answers for someone who has saved these target
 * titles and no other section: every other section is null until saved.
 */
export function profileWith(titles: string[]): ProfileBody {
  return {
    target_titles: titles,
    title_range: null,
    places: null,
    pay: null,
    skills: null,
    gaps: null,
    deal_breakers: null,
    companies: null,
    pace: null,
    own_rules: null,
  }
}

/** A profile whose every section has been saved, so none is null. */
export type FullProfile = {
  [Key in keyof ProfileBody]: NonNullable<ProfileBody[Key]>
}

/** A profile with every section saved, each holding something. */
export function fullProfile(): FullProfile {
  return {
    target_titles: ['Data Analyst'],
    title_range: { nearby_titles: ['Data Scientist'], lower_level_ok: true },
    places: {
      remote_ok: true,
      offices: [{ city: 'Boston', days_a_week: 3 }],
      states: ['MA', 'NY'],
      will_relocate: false,
      relocate_for: ['Example Corp'],
    },
    pay: { floor_usd: 90_000, ask_usd: 120_000 },
    skills: { skills: [{ name: 'Python', years: 5 }] },
    gaps: { apply_with: ['No degree'], trade_offs: ['A longer commute'] },
    deal_breakers: {
      industries: ['Gambling'],
      company_sizes: ['1-10', '10001+'],
      no_agencies: true,
    },
    companies: {
      watch: ['Example Corp'],
      applied: [{ company: 'Example Corp', title: 'Data Analyst' }],
    },
    pace: { leads_per_day: 10, brief_from_score: 4 },
    own_rules: { rules: ['No on-call rota'] },
  }
}

/** How one save route answers, given what was sent. */
export type Reply = (init?: RequestInit) => Promise<Response>

/** A body the contract allows, typed so it changes when the backend's does. */
export function answer(
  status: number,
  body: ProfileBody | SaveRefusalBody,
): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

/** A request that never answers, and fails the way fetch does when aborted. */
export function answerOnlyAbort(init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

/**
 * A reply that holds its answer until the test gives it, with the body sent;
 * `finish` answers the latest request.
 */
export function heldReply() {
  let finish: (response: Response) => void = () => {}
  const reply: Reply = () =>
    new Promise<Response>((resolve) => {
      finish = resolve
    })
  return { reply, finish: (response: Response) => finish(response) }
}

/**
 * Stands in for the service: the profile route answers `stored`, and each
 * save route as `saves` says, never answering when it says nothing.
 */
export function stubProfileService(
  stored: ProfileBody,
  saves: Partial<Record<SectionRoute, Reply>> = {},
) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/profile') {
      return answer(200, stored)
    }
    const route = Object.keys(saves).find((key) => url === `/api${key}`) as
      | SectionRoute
      | undefined
    if (url.startsWith('/api/profile/')) {
      const reply = route === undefined ? undefined : saves[route]
      return (reply ?? answerOnlyAbort)(init)
    }
    return Promise.reject(new TypeError(`unexpected request to ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The JSON bodies sent to one save route, in order. */
export function sentTo(
  fetchMock: ReturnType<typeof stubProfileService>,
  route: SectionRoute,
): unknown[] {
  return fetchMock.mock.calls
    .filter(([url]) => url === `/api${route}`)
    .map(([, init]) => JSON.parse(init?.body as string) as unknown)
}
