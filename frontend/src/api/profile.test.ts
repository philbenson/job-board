import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchProfile,
  saveSection,
  type ProfileBody,
  type SaveRefusalBody,
  type SectionBody,
  type SectionRoute,
  type StoredSection,
} from './profile.ts'
import { fullProfile, profileWith } from '../test/profileAnswers.ts'

const TOKEN = 'header.payload.signature'

const FULL = fullProfile()
const TOO_LONG = {
  detail: [
    {
      loc: ['body', 'titles', 0],
      msg: 'A target title can be at most 100 characters',
      type: 'target_title_too_long',
      input: 'x'.repeat(101),
    },
  ],
} satisfies SaveRefusalBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: ProfileBody | SaveRefusalBody): Response {
  return answerText(status, JSON.stringify(body))
}

// A body outside the contract, written out on purpose.
function answerText(status: number, text: string): Response {
  return new Response(text, {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// A request that never answers, and fails the way fetch does when aborted.
function answerOnlyAbort(_url: string, init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

function stubFetch(reply: (url: string, init?: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn(reply)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// The full profile as JSON, with one place in it changed by `change`, which
// may break the contract on purpose.
function fullWith(change: (profile: Record<string, any>) => void): string {
  const profile = structuredClone(FULL) as Record<string, any>
  change(profile)
  return JSON.stringify(profile)
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('fetchProfile', () => {
  it('reads every section from a 200, sending the token as a bearer token', async () => {
    let init: RequestInit | undefined
    const fetchMock = stubFetch(async (_url, given) => {
      init = given
      return answer(200, FULL)
    })

    await expect(fetchProfile(TOKEN)).resolves.toEqual({
      kind: 'loaded',
      profile: FULL,
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/profile', expect.anything())
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${TOKEN}`,
    )
  })

  it('reads a profile whose every section but the titles is unanswered', async () => {
    stubFetch(async () => answer(200, profileWith([])))

    await expect(fetchProfile(TOKEN)).resolves.toEqual({
      kind: 'loaded',
      profile: profileWith([]),
    })
  })

  it.each([
    ['a target title that is not text', (p: Record<string, any>) => (p.target_titles = ['a', 7])],
    ['target titles that are null', (p: Record<string, any>) => (p.target_titles = null)],
    ['a yes-or-no in the title range given as text', (p: Record<string, any>) => (p.title_range.lower_level_ok = 'true')],
    ['days in the office that are not whole', (p: Record<string, any>) => (p.places.offices[0].days_a_week = 2.5)],
    ['an office with a key it does not name', (p: Record<string, any>) => (p.places.offices[0].country = 'US')],
    ['a state that is not a code', (p: Record<string, any>) => (p.places.states = ['ZZ'])],
    ['a state code inherited by every object', (p: Record<string, any>) => (p.places.states = ['constructor'])],
    ['pay given as text', (p: Record<string, any>) => (p.pay.floor_usd = '90000')],
    ['a skill without its years', (p: Record<string, any>) => delete p.skills.skills[0].years],
    ['trade-offs that are not a list', (p: Record<string, any>) => (p.gaps.trade_offs = 'A longer commute')],
    ['a company size the backend does not offer', (p: Record<string, any>) => (p.deal_breakers.company_sizes = ['1-9'])],
    ['a job applied to with a key it does not name', (p: Record<string, any>) => (p.companies.applied[0].salary = 1)],
    ['a brief score given as text', (p: Record<string, any>) => (p.pace.brief_from_score = '4')],
    ['own rules with a key they do not name', (p: Record<string, any>) => (p.own_rules.notes = [])],
    ['a section that is missing', (p: Record<string, any>) => delete p.own_rules],
    ['a section that is a list', (p: Record<string, any>) => (p.pay = [1, 2])],
  ])('reports unavailable for %s', async (_case, change) => {
    stubFetch(async () => answerText(200, fullWith(change)))

    await expect(fetchProfile(TOKEN)).resolves.toBe('unavailable')
  })

  it.each([
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 503', () => answerText(503, '{"detail": "down"}')],
    ['a success code other than 200', () => answer(203, FULL)],
    ['a 200 that is empty', () => answerText(200, '{}')],
    ['a body that does not parse', () => answerText(200, 'Designer')],
    ['a body that is not an object', () => answerText(200, 'null')],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(fetchProfile(TOKEN)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the request fails', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(fetchProfile(TOKEN)).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable, not aborted', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    let result: unknown
    void fetchProfile(TOKEN, new AbortController().signal).then((read) => {
      result = read
    })

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it('reports aborted when the caller aborts', async () => {
    stubFetch(answerOnlyAbort)
    const controller = new AbortController()

    const result = fetchProfile(TOKEN, controller.signal)
    controller.abort()

    await expect(result).resolves.toBe('aborted')
  })
})

// One save: the route, its body, and the section the backend then holds.
function save<Route extends SectionRoute>(
  route: Route,
  body: SectionBody<Route>,
  stored: StoredSection<Route>,
) {
  return { route, body, stored, send: () => saveSection(TOKEN, route, body) }
}

const SAVES = [
  save('/profile/target-titles', { titles: FULL.target_titles }, FULL.target_titles),
  save('/profile/title-range', FULL.title_range, FULL.title_range),
  save('/profile/places', FULL.places, FULL.places),
  save('/profile/pay', FULL.pay, FULL.pay),
  save('/profile/skills', FULL.skills, FULL.skills),
  save('/profile/gaps', FULL.gaps, FULL.gaps),
  save('/profile/deal-breakers', FULL.deal_breakers, FULL.deal_breakers),
  save('/profile/companies', FULL.companies, FULL.companies),
  save('/profile/pace', FULL.pace, FULL.pace),
  save('/profile/own-rules', FULL.own_rules, FULL.own_rules),
]

describe('saveSection', () => {
  it.each(SAVES.map((one) => [one.route, one] as const))(
    'puts the body for %s as JSON with the bearer token and reads back the stored section',
    async (route, one) => {
      let init: RequestInit | undefined
      const fetchMock = stubFetch(async (_url, given) => {
        init = given
        return answer(200, FULL)
      })

      await expect(one.send()).resolves.toEqual({
        kind: 'saved',
        section: one.stored,
      })
      expect(fetchMock).toHaveBeenCalledWith(`/api${route}`, expect.anything())
      expect(init?.method).toBe('PUT')
      const headers = new Headers(init?.headers)
      expect(headers.get('Authorization')).toBe(`Bearer ${TOKEN}`)
      expect(headers.get('Content-Type')).toBe('application/json')
      expect(JSON.parse(init?.body as string)).toEqual(one.body)
    },
  )

  it('reads back the section as the backend stored it, not as it was sent', async () => {
    stubFetch(async () => answer(200, profileWith(['Designer'])))

    await expect(
      saveSection(TOKEN, '/profile/target-titles', { titles: ['Designer', ' designer '] }),
    ).resolves.toEqual({ kind: 'saved', section: ['Designer'] })
  })

  // A deploy can add a field while a page is open: the save is stored all
  // the same, and only the saved section's shape says what was stored.
  it.each([
    ['a section the page does not know', (p: Record<string, any>) => (p.scoring = { weights: [] })],
    ['a key another section does not name', (p: Record<string, any>) => (p.pay.bonus_usd = 1)],
    ['another section in a shape the page does not know', (p: Record<string, any>) => (p.skills = 'many')],
  ])('reads back the saved section from an answer with %s', async (_case, change) => {
    stubFetch(async () => answerText(200, fullWith(change)))

    await expect(saveSection(TOKEN, '/profile/places', FULL.places)).resolves.toEqual({
      kind: 'saved',
      section: FULL.places,
    })
  })

  it.each([
    ['a key the saved section does not name', (p: Record<string, any>) => (p.places.country = 'US')],
    ['a key an office does not name', (p: Record<string, any>) => (p.places.offices[0].country = 'US')],
    ['the saved section in another shape', (p: Record<string, any>) => (p.places.remote_ok = 'yes')],
  ])('reports unavailable for an answer with %s', async (_case, change) => {
    stubFetch(async () => answerText(200, fullWith(change)))

    await expect(saveSection(TOKEN, '/profile/places', FULL.places)).resolves.toBe('unavailable')
  })

  it('reports unavailable when the answer still holds the saved section as unanswered', async () => {
    stubFetch(async () => answer(200, profileWith(['Designer'])))

    await expect(
      saveSection(TOKEN, '/profile/pay', { floor_usd: 1, ask_usd: 2 }),
    ).resolves.toBe('unavailable')
  })

  it("reports the backend's rule for a 422 and where in the body it points", async () => {
    stubFetch(async () => answer(422, TOO_LONG))

    await expect(
      saveSection(TOKEN, '/profile/target-titles', { titles: ['x'.repeat(101)] }),
    ).resolves.toEqual({
      kind: 'refused',
      message: 'A target title can be at most 100 characters',
      at: ['titles', 0],
    })
  })

  it('reports a place inside one item of a list, as the backend names it', async () => {
    // As the backend answers an office whose city is too long.
    const refusal = {
      detail: [
        {
          loc: ['body', 'offices', 1, 'city'],
          msg: 'A city can be at most 100 characters',
          type: 'city_too_long',
        },
      ],
    } satisfies SaveRefusalBody
    stubFetch(async () => answer(422, refusal))

    await expect(saveSection(TOKEN, '/profile/places', FULL.places)).resolves.toEqual({
      kind: 'refused',
      message: 'A city can be at most 100 characters',
      at: ['offices', 1, 'city'],
    })
  })

  it.each([
    ['the whole body', ['body'], []],
    ['a place outside the body', ['query', 'titles'], []],
    ['a place with a part that is neither text nor a number', ['body', 'titles', null], []],
    ['a place that is not a list', 'body', []],
  ])('points nowhere for a 422 about %s', async (_case, loc, at) => {
    stubFetch(async () =>
      answerText(422, JSON.stringify({ detail: [{ loc, msg: 'Refused', type: 'refused' }] })),
    )

    await expect(
      saveSection(TOKEN, '/profile/target-titles', { titles: ['Designer'] }),
    ).resolves.toEqual({ kind: 'refused', message: 'Refused', at })
  })

  it.each([
    ['a 401', () => answerText(401, '{"detail": "sign-in required"}')],
    ['a 500', () => answerText(500, 'Internal Server Error')],
    ['a 200 without the titles', () => answerText(200, '{}')],
    ['a 200 that is not an object', () => answerText(200, 'null')],
    ['a 422 without a detail list', () => answerText(422, '{"detail": "no"}')],
    ['a 422 with an empty detail list', () => answerText(422, '{"detail": []}')],
    ['a 422 whose first entry has no message', () => answerText(422, '{"detail": [{"loc": []}]}')],
    ['a 422 that does not parse', () => answerText(422, 'Unprocessable')],
  ])('reports unavailable for %s', async (_case, reply) => {
    stubFetch(async () => reply())

    await expect(
      saveSection(TOKEN, '/profile/target-titles', { titles: ['Designer'] }),
    ).resolves.toBe('unavailable')
  })

  it('gives up after five seconds and reports unavailable', async () => {
    vi.useFakeTimers()
    stubFetch(answerOnlyAbort)
    let result: unknown
    void saveSection(TOKEN, '/profile/pace', FULL.pace).then((saved) => {
      result = saved
    })

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it('reports aborted, not saved, for an answer that lands after the caller aborts', async () => {
    const controller = new AbortController()
    stubFetch(async () => {
      controller.abort()
      return answer(200, FULL)
    })

    await expect(
      saveSection(TOKEN, '/profile/pace', FULL.pace, controller.signal),
    ).resolves.toBe('aborted')
  })
})
