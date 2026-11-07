import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SaveRefusalBody, SectionRoute } from '../api/profile.ts'
import { ProfilePanel } from './ProfilePanel.tsx'
import {
  answer,
  fullProfile,
  profileWith,
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
