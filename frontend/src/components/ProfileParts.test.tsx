import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProfileBody, SaveRefusalBody, SectionRoute } from '../api/profile.ts'
import { ProfilePanel } from './ProfilePanel.tsx'
import {
  answer,
  fullProfile,
  profileWith,
  type Reply,
  sentTo,
  stubProfileService,
} from '../test/profileAnswers.ts'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const user = userEvent.setup()

// A part of the panel, found by its heading.
function part(heading: string) {
  return within(screen.getByRole('region', { name: heading }))
}

async function loaded(): Promise<void> {
  await screen.findByRole('heading', { level: 3, name: 'Target titles' })
}

async function type(heading: string, label: string, text: string): Promise<void> {
  await user.type(part(heading).getByRole('textbox', { name: label }), text)
}

async function tick(heading: string, label: string): Promise<void> {
  await user.click(part(heading).getByRole('checkbox', { name: label }))
}

async function save(heading: string): Promise<void> {
  await user.click(part(heading).getByRole('button', { name: 'Save' }))
}

// Every item shown in the part, as text, in order.
function shownIn(heading: string, list: string): string[] {
  return within(part(heading).getByRole('list', { name: list }))
    .getAllByRole('listitem')
    .map((item) => item.firstChild?.textContent ?? '')
}

function refusal(loc: (string | number)[], msg: string): SaveRefusalBody {
  return { detail: [{ loc, msg, type: 'refused' }] }
}

describe('the profile parts', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue('header.payload.signature')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('each part sends its whole body', () => {
    async function sentBy(route: SectionRoute, fill: () => Promise<void>, heading: string) {
      const fetchMock = stubProfileService(profileWith(['Designer']))
      render(<ProfilePanel />)
      await loaded()
      await fill()
      await save(heading)
      return sentTo(fetchMock, route)
    }

    it('nearby titles', async () => {
      const sent = await sentBy(
        '/profile/title-range',
        async () => {
          await type('Nearby titles', 'Add a nearby title', 'Data Scientist{Enter}')
          await type('Nearby titles', 'Add a nearby title', ' Analytics Engineer {Enter}')
          await tick('Nearby titles', 'A lower level than my target titles is fine')
        },
        'Nearby titles',
      )

      expect(sent).toEqual([
        { nearby_titles: ['Data Scientist', 'Analytics Engineer'], lower_level_ok: true },
      ])
    })

    it('places', async () => {
      const sent = await sentBy(
        '/profile/places',
        async () => {
          await tick('Places', 'A fully remote role is fine')
          await type('Places', 'City', 'Boston')
          await user.selectOptions(
            part('Places').getByRole('combobox', { name: 'Days a week in the office' }),
            '3',
          )
          await user.click(
            within(part('Places').getByRole('group', { name: 'Offices you would go into' })).getByRole('button', { name: 'Add' }),
          )
          await type('Places', 'City', 'Chicago')
          await user.selectOptions(
            part('Places').getByRole('combobox', { name: 'Days a week in the office' }),
            '5 (on site)',
          )
          await type('Places', 'City', '{Enter}')
          await tick('Places', 'New York')
          await tick('Places', 'Massachusetts')
          await type('Places', 'Add a company you would move for', 'Example Corp{Enter}')
        },
        'Places',
      )

      expect(sent).toEqual([
        {
          remote_ok: true,
          offices: [
            { city: 'Boston', days_a_week: 3 },
            { city: 'Chicago', days_a_week: 5 },
          ],
          states: ['NY', 'MA'],
          will_relocate: false,
          relocate_for: ['Example Corp'],
        },
      ])
    })

    it('pay, with the commas dropped', async () => {
      const sent = await sentBy(
        '/profile/pay',
        async () => {
          await type('Pay', 'Lowest base pay you would take, in US dollars a year', '90,000')
          await type('Pay', 'Base pay you would ask for, in US dollars a year', ' 120000 ')
        },
        'Pay',
      )

      expect(sent).toEqual([{ floor_usd: 90_000, ask_usd: 120_000 }])
    })

    it('skills, under a year said as such', async () => {
      const sent = await sentBy(
        '/profile/skills',
        async () => {
          await type('Skills', 'Skill', 'Python')
          await type('Skills', 'Years', ' 5 {Enter}')
          await type('Skills', 'Skill', 'SQL')
          await type('Skills', 'Years', '0{Enter}')
          await type('Skills', 'Skill', 'Excel')
          await type('Skills', 'Years', '1{Enter}')
          expect(shownIn('Skills', 'Your skills')).toEqual([
            'Python, 5 years',
            'SQL, under a year',
            'Excel, 1 year',
          ])
        },
        'Skills',
      )

      expect(sent).toEqual([
        {
          skills: [
            { name: 'Python', years: 5 },
            { name: 'SQL', years: 0 },
            { name: 'Excel', years: 1 },
          ],
        },
      ])
    })

    it('gaps and trade-offs', async () => {
      const sent = await sentBy(
        '/profile/gaps',
        async () => {
          await type('Gaps and trade-offs', 'Add a gap you would apply with', 'No degree{Enter}')
          await type('Gaps and trade-offs', 'Add a trade-off you would make', 'A longer commute{Enter}')
          await type('Gaps and trade-offs', 'Add a trade-off you would make', 'Less pay{Enter}')
        },
        'Gaps and trade-offs',
      )

      expect(sent).toEqual([
        { apply_with: ['No degree'], trade_offs: ['A longer commute', 'Less pay'] },
      ])
    })

    it('deal-breakers', async () => {
      const sent = await sentBy(
        '/profile/deal-breakers',
        async () => {
          await type('Deal-breakers', 'Add an industry you will not work in', 'Gambling{Enter}')
          await tick('Deal-breakers', '10,001 or more people')
          await tick('Deal-breakers', '1 to 10 people')
          await tick('Deal-breakers', 'No recruiting agencies')
        },
        'Deal-breakers',
      )

      expect(sent).toEqual([
        { industries: ['Gambling'], company_sizes: ['10001+', '1-10'], no_agencies: true },
      ])
    })

    it('companies', async () => {
      const sent = await sentBy(
        '/profile/companies',
        async () => {
          await type('Companies', 'Add a company to watch', 'Example Corp{Enter}')
          await type('Companies', 'Company', 'Example Corp')
          await type('Companies', 'Job title', ' Data Analyst {Enter}')
          await type('Companies', 'Company', 'Example Corp')
          await type('Companies', 'Job title', 'Data Scientist{Enter}')
          expect(shownIn('Companies', 'Your applications')).toEqual([
            'Data Analyst at Example Corp',
            'Data Scientist at Example Corp',
          ])
          expect(
            part('Companies').getByRole('button', { name: 'Remove Data Analyst at Example Corp' }),
          ).toBeInTheDocument()
        },
        'Companies',
      )

      expect(sent).toEqual([
        {
          watch: ['Example Corp'],
          applied: [
            { company: 'Example Corp', title: 'Data Analyst' },
            { company: 'Example Corp', title: 'Data Scientist' },
          ],
        },
      ])
    })

    it('pace, no briefs sent as none', async () => {
      const sent = await sentBy(
        '/profile/pace',
        async () => {
          await type('Pace', 'Leads a day', '12')
          expect(
            part('Pace').getByRole('combobox', { name: 'Write a brief for postings scored at least' }),
          ).toHaveValue('')
        },
        'Pace',
      )

      expect(sent).toEqual([{ leads_per_day: 12, brief_from_score: null }])
    })

    it('pace, with a score for briefs', async () => {
      const sent = await sentBy(
        '/profile/pace',
        async () => {
          await type('Pace', 'Leads a day', '5')
          await user.selectOptions(
            part('Pace').getByRole('combobox', { name: 'Write a brief for postings scored at least' }),
            '4',
          )
        },
        'Pace',
      )

      expect(sent).toEqual([{ leads_per_day: 5, brief_from_score: 4 }])
    })

    it('your own rules', async () => {
      const sent = await sentBy(
        '/profile/own-rules',
        async () => {
          await type('Your own rules', 'Add a rule', 'No on-call rota{Enter}')
        },
        'Your own rules',
      )

      expect(sent).toEqual([{ rules: ['No on-call rota'] }])
    })
  })

  it('holds a save whose number is blank or not whole, saying which', async () => {
    const fetchMock = stubProfileService(profileWith([]))
    render(<ProfilePanel />)
    await loaded()
    const [notice] = part('Pay').getAllByRole('status')

    await save('Pay')
    expect(notice).toHaveTextContent('Enter the lowest base pay as a whole number')
    await type('Pay', 'Lowest base pay you would take, in US dollars a year', '90000')
    await type('Pay', 'Base pay you would ask for, in US dollars a year', '1.5e5')
    await save('Pay')
    expect(notice).toHaveTextContent('Enter the base pay you would ask for as a whole number')

    expect(sentTo(fetchMock, '/profile/pay')).toEqual([])
  })

  it('adds no skill whose years are blank or not whole, saying so', async () => {
    const fetchMock = stubProfileService(profileWith([]))
    render(<ProfilePanel />)
    await loaded()
    const [notice] = part('Skills').getAllByRole('status')

    await type('Skills', 'Skill', 'Python{Enter}')
    expect(notice).toHaveTextContent('Enter years as a whole number')
    await type('Skills', 'Years', '2.5{Enter}')
    expect(notice).toHaveTextContent('Enter years as a whole number')
    expect(part('Skills').queryByRole('list')).not.toBeInTheDocument()
    await save('Skills')

    expect(sentTo(fetchMock, '/profile/skills')).toEqual([{ skills: [] }])
  })

  it('holds a pace save whose leads a day is blank or not whole', async () => {
    const fetchMock = stubProfileService(profileWith([]))
    render(<ProfilePanel />)
    await loaded()
    const [notice] = part('Pace').getAllByRole('status')

    await save('Pace')
    expect(notice).toHaveTextContent('Enter leads a day as a whole number')
    await type('Pace', 'Leads a day', 'ten')
    await save('Pace')
    expect(notice).toHaveTextContent('Enter leads a day as a whole number')

    expect(sentTo(fetchMock, '/profile/pace')).toEqual([])
  })

  it('refuses a job applied to twice, by company and title together', async () => {
    stubProfileService(profileWith([]))
    render(<ProfilePanel />)
    await loaded()
    const [notice] = part('Companies').getAllByRole('status')

    await type('Companies', 'Company', 'Example Corp')
    await type('Companies', 'Job title', 'Data Analyst{Enter}')
    await type('Companies', 'Company', 'example corp')
    await type('Companies', 'Job title', 'DATA ANALYST{Enter}')

    expect(notice).toHaveTextContent('Data Analyst at Example Corp is already in your list')
    expect(shownIn('Companies', 'Your applications')).toEqual(['Data Analyst at Example Corp'])
  })

  it('shows each section as stored, its numbers grouped, once read', async () => {
    stubProfileService(fullProfile())
    render(<ProfilePanel />)
    await loaded()

    expect(shownIn('Nearby titles', 'Your nearby titles')).toEqual(['Data Scientist'])
    expect(part('Nearby titles').getByRole('checkbox', { name: 'A lower level than my target titles is fine' })).toBeChecked()
    expect(shownIn('Places', 'Your offices')).toEqual(['Boston, 3 days a week'])
    expect(part('Places').getByRole('checkbox', { name: 'Massachusetts' })).toBeChecked()
    expect(part('Places').getByRole('checkbox', { name: 'Ohio' })).not.toBeChecked()
    expect(shownIn('Places', 'Companies you would move for')).toEqual(['Example Corp'])
    expect(part('Pay').getByRole('textbox', { name: 'Lowest base pay you would take, in US dollars a year' })).toHaveValue('90,000')
    expect(shownIn('Skills', 'Your skills')).toEqual(['Python, 5 years'])
    expect(shownIn('Gaps and trade-offs', 'Gaps you would apply with')).toEqual(['No degree'])
    expect(shownIn('Gaps and trade-offs', 'Trade-offs you would make')).toEqual(['A longer commute'])
    expect(shownIn('Deal-breakers', 'Industries you will not work in')).toEqual(['Gambling'])
    expect(part('Deal-breakers').getByRole('checkbox', { name: '1 to 10 people' })).toBeChecked()
    expect(part('Deal-breakers').getByRole('checkbox', { name: '11 to 50 people' })).not.toBeChecked()
    expect(part('Deal-breakers').getByRole('checkbox', { name: 'No recruiting agencies' })).toBeChecked()
    expect(shownIn('Companies', 'Companies you watch')).toEqual(['Example Corp'])
    expect(shownIn('Companies', 'Your applications')).toEqual(['Data Analyst at Example Corp'])
    expect(part('Pace').getByRole('textbox', { name: 'Leads a day' })).toHaveValue('10')
    expect(part('Pace').getByRole('combobox', { name: 'Write a brief for postings scored at least' })).toHaveValue('4')
    expect(shownIn('Your own rules', 'Your rules')).toEqual(['No on-call rota'])
    expect(screen.queryByText('Not answered yet.')).not.toBeInTheDocument()
  })

  it('shows the section as the backend stored it in place of what was sent', async () => {
    // The backend folds case more fully than the page does, so it keeps one
    // of two titles the page let through as different.
    stubProfileService(profileWith([]), {
      '/profile/title-range': () =>
        answer(200, {
          ...profileWith([]),
          title_range: { nearby_titles: ['Straße manager'], lower_level_ok: false },
        }),
    })
    render(<ProfilePanel />)
    await loaded()

    await type('Nearby titles', 'Add a nearby title', 'Straße manager{Enter}')
    await type('Nearby titles', 'Add a nearby title', 'STRASSE MANAGER{Enter}')
    expect(shownIn('Nearby titles', 'Your nearby titles')).toHaveLength(2)
    await save('Nearby titles')

    expect(await part('Nearby titles').findByText('Saved')).toBeInTheDocument()
    expect(shownIn('Nearby titles', 'Your nearby titles')).toEqual(['Straße manager'])
  })

  it("shows a refusal of one office's city, naming that city alone", async () => {
    stubProfileService(profileWith([]), {
      '/profile/places': () =>
        answer(422, refusal(['body', 'offices', 1, 'city'], 'A city can be at most 100 characters')),
    })
    render(<ProfilePanel />)
    await loaded()

    await type('Places', 'City', 'Boston{Enter}')
    await type('Places', 'City', 'Chicago{Enter}')
    await save('Places')

    const [, saveLine] = part('Places').getAllByRole('status')
    expect(await part('Places').findByText('A city can be at most 100 characters: Chicago')).toBe(saveLine)
    expect(shownIn('Places', 'Your offices')).toEqual(['Boston, 1 day a week', 'Chicago, 1 day a week'])
  })

  it.each([
    [['body', 'ask_usd'], 'The ask cannot be below the floor: Base pay you would ask for, in US dollars a year'],
    [['body'], 'The ask cannot be below the floor'],
    [['body', 'bonus_usd'], 'The ask cannot be below the floor'],
  ])('names a single field by its label when a refusal points at it (%j)', async (loc, said) => {
    stubProfileService(profileWith([]), {
      '/profile/pay': () => answer(422, refusal(loc, 'The ask cannot be below the floor')),
    })
    render(<ProfilePanel />)
    await loaded()

    await type('Pay', 'Lowest base pay you would take, in US dollars a year', '2')
    await type('Pay', 'Base pay you would ask for, in US dollars a year', '1')
    await save('Pay')

    expect(await part('Pay').findByText(said)).toBeInTheDocument()
  })

  it("names a skill when a refusal points at its years", async () => {
    stubProfileService(profileWith([]), {
      '/profile/skills': () =>
        answer(422, refusal(['body', 'skills', 1, 'years'], 'Input should be less than or equal to 60')),
    })
    render(<ProfilePanel />)
    await loaded()

    await type('Skills', 'Skill', 'Python')
    await type('Skills', 'Years', '5{Enter}')
    await type('Skills', 'Skill', 'SQL')
    await type('Skills', 'Years', '61{Enter}')
    await save('Skills')

    expect(
      await part('Skills').findByText('Input should be less than or equal to 60: SQL'),
    ).toBeInTheDocument()
  })

  it("names a job applied to by its company when a refusal points into it", async () => {
    stubProfileService(profileWith([]), {
      '/profile/companies': () =>
        answer(422, refusal(['body', 'applied', 0, 'title'], 'A job title cannot be blank')),
    })
    render(<ProfilePanel />)
    await loaded()

    await type('Companies', 'Company', 'Example Corp{Enter}')
    await save('Companies')

    expect(
      await part('Companies').findByText('A job title cannot be blank: Example Corp'),
    ).toBeInTheDocument()
  })

  it('names a state by its name when a refusal points at it', async () => {
    stubProfileService(profileWith([]), {
      '/profile/places': () =>
        answer(422, refusal(['body', 'states', 0], 'A state must be the two-letter postal code of a US state or DC')),
    })
    render(<ProfilePanel />)
    await loaded()

    await tick('Places', 'Ohio')
    await save('Places')

    expect(
      await part('Places').findByText('A state must be the two-letter postal code of a US state or DC: Ohio'),
    ).toBeInTheDocument()
  })

  it('says a failed save keeps the changes, in the words of its part', async () => {
    stubProfileService(profileWith([]), {
      '/profile/places': () => Promise.resolve(new Response('down', { status: 503 })),
    })
    render(<ProfilePanel />)
    await loaded()

    await tick('Places', 'I would move for a role')
    await save('Places')

    expect(
      await part('Places').findByText('Could not save your places; your changes are still here'),
    ).toBeInTheDocument()
    expect(part('Places').getByRole('checkbox', { name: 'I would move for a role' })).toBeChecked()
  })

  it('shows markup typed into a list as text', async () => {
    stubProfileService(profileWith([]))
    render(<ProfilePanel />)
    await loaded()
    const markup = '<img src=x onerror=alert(1)><b>Lead</b>'

    await type('Nearby titles', 'Add a nearby title', `${markup}{Enter}`)

    expect(shownIn('Nearby titles', 'Your nearby titles')).toEqual([markup])
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
  })
})

// Loads the panel on `stored`, with each of `saves` answering its route.
async function panelOn(
  stored: ProfileBody,
  saves: Partial<Record<SectionRoute, Reply>> = {},
): Promise<ReturnType<typeof stubProfileService>> {
  const fetchMock = stubProfileService(stored, saves)
  render(<ProfilePanel />)
  await loaded()
  return fetchMock
}

// Pastes rather than types, since a list's longest text runs to hundreds
// of characters.
async function paste(heading: string, label: string, text: string): Promise<void> {
  await user.click(part(heading).getByRole('textbox', { name: label }))
  await user.paste(text)
}

async function enter(heading: string, label: string, text: string): Promise<void> {
  await paste(heading, label, text)
  await user.keyboard('{Enter}')
}

function noticeOf(heading: string): HTMLElement {
  const [notice] = part(heading).getAllByRole('status')
  if (notice === undefined) {
    throw new Error(`${heading} has no notice line`)
  }
  return notice
}

describe('the profile parts, past the first visit', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue('header.payload.signature')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // Each part sends one section and the backend answers another: the part
  // must show what the backend stored, never what it sent.
  type StoredCase = {
    heading: string
    route: SectionRoute
    edit: () => Promise<void>
    answered: Partial<ProfileBody>
    shows: () => void
  }

  const storedCases: StoredCase[] = [
    {
      heading: 'Places',
      route: '/profile/places',
      edit: async () => {
        await type('Places', 'City', 'boston{Enter}')
        await tick('Places', 'Ohio')
      },
      answered: {
        places: {
          remote_ok: true,
          offices: [{ city: 'Boston', days_a_week: 2 }],
          states: ['NY'],
          will_relocate: true,
          relocate_for: [],
        },
      },
      shows: () => {
        expect(shownIn('Places', 'Your offices')).toEqual(['Boston, 2 days a week'])
        expect(part('Places').getByRole('checkbox', { name: 'New York' })).toBeChecked()
        expect(part('Places').getByRole('checkbox', { name: 'Ohio' })).not.toBeChecked()
        expect(part('Places').getByRole('checkbox', { name: 'A fully remote role is fine' })).toBeChecked()
        expect(part('Places').getByRole('checkbox', { name: 'I would move for a role' })).toBeChecked()
      },
    },
    {
      heading: 'Pay',
      route: '/profile/pay',
      edit: async () => {
        await type('Pay', 'Lowest base pay you would take, in US dollars a year', '90000')
        await type('Pay', 'Base pay you would ask for, in US dollars a year', '120000')
      },
      answered: { pay: { floor_usd: 95_000, ask_usd: 125_000 } },
      shows: () => {
        expect(part('Pay').getByRole('textbox', { name: 'Lowest base pay you would take, in US dollars a year' })).toHaveValue('95,000')
        expect(part('Pay').getByRole('textbox', { name: 'Base pay you would ask for, in US dollars a year' })).toHaveValue('125,000')
      },
    },
    {
      heading: 'Skills',
      route: '/profile/skills',
      edit: async () => {
        await type('Skills', 'Skill', 'Go')
        await type('Skills', 'Years', '3{Enter}')
      },
      answered: { skills: { skills: [{ name: 'Go', years: 4 }] } },
      shows: () => {
        expect(shownIn('Skills', 'Your skills')).toEqual(['Go, 4 years'])
      },
    },
    {
      heading: 'Gaps and trade-offs',
      route: '/profile/gaps',
      edit: async () => {
        await type('Gaps and trade-offs', 'Add a gap you would apply with', 'No degree{Enter}')
        await type('Gaps and trade-offs', 'Add a trade-off you would make', 'Less pay{Enter}')
      },
      answered: { gaps: { apply_with: ['No degree yet'], trade_offs: [] } },
      shows: () => {
        expect(shownIn('Gaps and trade-offs', 'Gaps you would apply with')).toEqual(['No degree yet'])
        expect(part('Gaps and trade-offs').queryByRole('list', { name: 'Trade-offs you would make' })).not.toBeInTheDocument()
      },
    },
    {
      heading: 'Deal-breakers',
      route: '/profile/deal-breakers',
      edit: async () => {
        await type('Deal-breakers', 'Add an industry you will not work in', 'Straße{Enter}')
        await type('Deal-breakers', 'Add an industry you will not work in', 'STRASSE{Enter}')
        await tick('Deal-breakers', '1 to 10 people')
      },
      answered: {
        deal_breakers: { industries: ['Straße'], company_sizes: ['51-200'], no_agencies: true },
      },
      shows: () => {
        expect(shownIn('Deal-breakers', 'Industries you will not work in')).toEqual(['Straße'])
        expect(part('Deal-breakers').getByRole('checkbox', { name: '1 to 10 people' })).not.toBeChecked()
        expect(part('Deal-breakers').getByRole('checkbox', { name: '51 to 200 people' })).toBeChecked()
        expect(part('Deal-breakers').getByRole('checkbox', { name: 'No recruiting agencies' })).toBeChecked()
      },
    },
    {
      heading: 'Companies',
      route: '/profile/companies',
      edit: async () => {
        await type('Companies', 'Add a company to watch', 'example corp{Enter}')
        await type('Companies', 'Company', 'Example Corp')
        await type('Companies', 'Job title', 'Data Analyst{Enter}')
      },
      answered: {
        companies: {
          watch: ['Example Corp'],
          applied: [{ company: 'Example Corp', title: 'Senior Data Analyst' }],
        },
      },
      shows: () => {
        expect(shownIn('Companies', 'Companies you watch')).toEqual(['Example Corp'])
        expect(shownIn('Companies', 'Your applications')).toEqual(['Senior Data Analyst at Example Corp'])
      },
    },
    {
      heading: 'Pace',
      route: '/profile/pace',
      edit: async () => {
        await type('Pace', 'Leads a day', '12')
      },
      answered: { pace: { leads_per_day: 10, brief_from_score: 3 } },
      shows: () => {
        expect(part('Pace').getByRole('textbox', { name: 'Leads a day' })).toHaveValue('10')
        expect(part('Pace').getByRole('combobox', { name: 'Write a brief for postings scored at least' })).toHaveValue('3')
      },
    },
    {
      heading: 'Your own rules',
      route: '/profile/own-rules',
      edit: async () => {
        await type('Your own rules', 'Add a rule', 'No on-call rota{Enter}')
        await type('Your own rules', 'Add a rule', 'No travel{Enter}')
      },
      answered: { own_rules: { rules: ['No on-call rota'] } },
      shows: () => {
        expect(shownIn('Your own rules', 'Your rules')).toEqual(['No on-call rota'])
      },
    },
  ]

  it.each(storedCases)('$heading shows the section as stored, not as sent', async (stored) => {
    await panelOn(profileWith([]), {
      [stored.route]: () => answer(200, { ...profileWith([]), ...stored.answered }),
    })

    await stored.edit()
    await save(stored.heading)

    expect(await part(stored.heading).findByText('Saved')).toBeInTheDocument()
    stored.shows()
  })

  // One row per list: the backend's cap and longest length, hard-coded from
  // profile_sections.py, so a page constant that drifts from it goes red.
  type ListCase = {
    list: string
    heading: string
    cap: number
    longest: number
    capSaid: string
    tooLong: (text: string) => string
    filled: (count: number) => Partial<ProfileBody>
    add: (text: string) => Promise<void>
  }

  const named = (count: number, stem: string): string[] =>
    Array.from({ length: count }, (_, at) => `${stem} ${at + 1}`)

  const listCases: ListCase[] = [
    {
      list: 'target titles',
      heading: 'Target titles',
      cap: 20,
      longest: 100,
      capSaid: 'You can list at most 20 target titles',
      tooLong: (text) => `A target title can be at most 100 characters: ${text}`,
      filled: (count) => ({ target_titles: named(count, 'Title') }),
      add: (text) => enter('Target titles', 'Add a target title', text),
    },
    {
      list: 'nearby titles',
      heading: 'Nearby titles',
      cap: 20,
      longest: 100,
      capSaid: 'You can list at most 20 nearby titles',
      tooLong: (text) => `A nearby title can be at most 100 characters: ${text}`,
      filled: (count) => ({ title_range: { nearby_titles: named(count, 'Title'), lower_level_ok: false } }),
      add: (text) => enter('Nearby titles', 'Add a nearby title', text),
    },
    {
      list: 'offices',
      heading: 'Places',
      cap: 20,
      longest: 100,
      capSaid: 'You can list at most 20 offices',
      tooLong: (text) => `A city can be at most 100 characters: ${text}`,
      filled: (count) => ({
        places: {
          remote_ok: false,
          offices: named(count, 'City').map((city) => ({ city, days_a_week: 1 })),
          states: [],
          will_relocate: false,
          relocate_for: [],
        },
      }),
      add: (text) => enter('Places', 'City', text),
    },
    {
      list: 'companies you would move for',
      heading: 'Places',
      cap: 20,
      longest: 100,
      capSaid: 'You can list at most 20 companies you would move for',
      tooLong: (text) => `A company can be at most 100 characters: ${text}`,
      filled: (count) => ({
        places: {
          remote_ok: false,
          offices: [],
          states: [],
          will_relocate: false,
          relocate_for: named(count, 'Company'),
        },
      }),
      add: (text) => enter('Places', 'Add a company you would move for', text),
    },
    {
      list: 'skills',
      heading: 'Skills',
      cap: 100,
      longest: 60,
      capSaid: 'You can list at most 100 skills',
      tooLong: (text) => `A skill can be at most 60 characters: ${text}`,
      filled: (count) => ({
        skills: { skills: named(count, 'Skill').map((name) => ({ name, years: 1 })) },
      }),
      add: async (text) => {
        await paste('Skills', 'Skill', text)
        await type('Skills', 'Years', '1{Enter}')
      },
    },
    {
      list: 'gaps',
      heading: 'Gaps and trade-offs',
      cap: 20,
      longest: 200,
      capSaid: 'You can list at most 20 gaps',
      tooLong: (text) => `A gap can be at most 200 characters: ${text}`,
      filled: (count) => ({ gaps: { apply_with: named(count, 'Gap'), trade_offs: [] } }),
      add: (text) => enter('Gaps and trade-offs', 'Add a gap you would apply with', text),
    },
    {
      list: 'trade-offs',
      heading: 'Gaps and trade-offs',
      cap: 20,
      longest: 200,
      capSaid: 'You can list at most 20 trade-offs',
      tooLong: (text) => `A trade-off can be at most 200 characters: ${text}`,
      filled: (count) => ({ gaps: { apply_with: [], trade_offs: named(count, 'Trade-off') } }),
      add: (text) => enter('Gaps and trade-offs', 'Add a trade-off you would make', text),
    },
    {
      list: 'industries',
      heading: 'Deal-breakers',
      cap: 30,
      longest: 100,
      capSaid: 'You can list at most 30 industries',
      tooLong: (text) => `An industry can be at most 100 characters: ${text}`,
      filled: (count) => ({
        deal_breakers: { industries: named(count, 'Industry'), company_sizes: [], no_agencies: false },
      }),
      add: (text) => enter('Deal-breakers', 'Add an industry you will not work in', text),
    },
    {
      list: 'companies to watch',
      heading: 'Companies',
      cap: 30,
      longest: 100,
      capSaid: 'You can list at most 30 companies to watch',
      tooLong: (text) => `A company can be at most 100 characters: ${text}`,
      filled: (count) => ({ companies: { watch: named(count, 'Company'), applied: [] } }),
      add: (text) => enter('Companies', 'Add a company to watch', text),
    },
    {
      list: 'jobs applied to, by company',
      heading: 'Companies',
      cap: 50,
      longest: 100,
      capSaid: 'You can list at most 50 jobs applied to',
      tooLong: (text) => `A company can be at most 100 characters: ${text}`,
      filled: (count) => ({
        companies: {
          watch: [],
          applied: named(count, 'Company').map((company) => ({ company, title: 'Analyst' })),
        },
      }),
      add: async (text) => {
        await paste('Companies', 'Company', text)
        await type('Companies', 'Job title', 'Analyst{Enter}')
      },
    },
    {
      list: 'jobs applied to, by title',
      heading: 'Companies',
      cap: 50,
      longest: 100,
      capSaid: 'You can list at most 50 jobs applied to',
      tooLong: (text) => `A job title can be at most 100 characters: ${text}`,
      filled: (count) => ({
        companies: {
          watch: [],
          applied: named(count, 'Title').map((title) => ({ company: 'Example Corp', title })),
        },
      }),
      add: async (text) => {
        await type('Companies', 'Company', 'Example Corp')
        await enter('Companies', 'Job title', text)
      },
    },
    {
      list: 'rules',
      heading: 'Your own rules',
      cap: 20,
      longest: 300,
      capSaid: 'You can list at most 20 rules',
      tooLong: (text) => `A rule can be at most 300 characters: ${text}`,
      filled: (count) => ({ own_rules: { rules: named(count, 'Rule') } }),
      add: (text) => enter('Your own rules', 'Add a rule', text),
    },
  ]

  it.each(listCases)('refuses one past the cap of $list, in its own words', async (row) => {
    await panelOn({ ...profileWith([]), ...row.filled(row.cap) })

    await row.add('One more')

    expect(noticeOf(row.heading)).toHaveTextContent(row.capSaid)
  })

  it.each(listCases)('takes $list at the longest length and refuses one past it', async (row) => {
    await panelOn(profileWith([]))
    // The last character is outside the basic plane: two UTF-16 units, one
    // character to the backend.
    const longest = `${'a'.repeat(row.longest - 1)}😀`
    const tooLong = `${'b'.repeat(row.longest)}😀`

    await row.add(longest)
    expect(noticeOf(row.heading)).toHaveTextContent(/^$/)
    await row.add(tooLong)

    expect(noticeOf(row.heading)).toHaveTextContent(row.tooLong(tooLong))
  })

  it.each([
    ['offices', 'Places', 'City', 'Boston', 'BOSTON'],
    ['skills', 'Skills', 'Skill', 'Python', 'python'],
  ])('refuses a repeat in %s whatever its case', async (_list, heading, label, first, again) => {
    await panelOn(profileWith([]))
    const addPair = async (text: string): Promise<void> => {
      await type(heading, label, text)
      if (heading === 'Skills') {
        await type(heading, 'Years', '1')
      }
      await type(heading, label, '{Enter}')
    }

    await addPair(first)
    await addPair(again)

    expect(noticeOf(heading)).toHaveTextContent(`${first} is already in your list`)
  })

  it('shows markup typed into a pair as text', async () => {
    await panelOn(profileWith([]))
    const markup = '<img src=x onerror=alert(1)><b>Lead</b>'

    await type('Places', 'City', `${markup}{Enter}`)
    await type('Companies', 'Company', markup)
    await type('Companies', 'Job title', `${markup}{Enter}`)

    expect(shownIn('Places', 'Your offices')).toEqual([`${markup}, 1 day a week`])
    expect(shownIn('Companies', 'Your applications')).toEqual([`${markup} at ${markup}`])
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(document.querySelector('b')).toBeNull()
  })

  it('clears "Saved" and the notice once the part is edited again', async () => {
    await panelOn(profileWith([]), {
      '/profile/title-range': () =>
        answer(200, {
          ...profileWith([]),
          title_range: { nearby_titles: ['Data Scientist'], lower_level_ok: false },
        }),
    })
    const [notice, saveLine] = part('Nearby titles').getAllByRole('status')

    await type('Nearby titles', 'Add a nearby title', 'Data Scientist{Enter}')
    await save('Nearby titles')
    expect(await part('Nearby titles').findByText('Saved')).toBe(saveLine)
    await type('Nearby titles', 'Add a nearby title', 'data scientist{Enter}')
    expect(notice).toHaveTextContent('Data Scientist is already in your list')
    expect(saveLine).toHaveTextContent('Saved')
    await tick('Nearby titles', 'A lower level than my target titles is fine')

    expect(notice).toHaveTextContent(/^$/)
    expect(saveLine).toHaveTextContent(/^$/)
  })
})
