import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProfileBody, SaveRefusalBody, TargetTitlesBody } from '../api/profile.ts'
import { SAVED_SECTIONS } from '../api/interview.ts'
import { ProfilePanel } from './ProfilePanel.tsx'
import { SECTION_HEADINGS } from './sectionHeadings.ts'
import {
  answer,
  heldReply,
  profileWith,
  sentTo,
  stubProfileService,
  type Reply,
} from '../test/profileAnswers.ts'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const SESSION_TOKEN = 'header.payload.signature'

const LOADING = 'Loading your profile…'
const NOT_LOADED = 'Could not load your profile. Reload the page to try again.'
const NONE_YET = 'No target titles yet'
const AT_MOST_TWENTY = 'You can list at most 20 target titles'
const SAVED = 'Saved'
const SAVING = 'Saving…'
const NOT_SAVED = 'Could not save your target titles; your changes are still here'

// The profile route answers with `stored` titles and no other section; the
// target titles' route as the test says.
function service(stored: string[], save?: Reply) {
  return stubProfileService(
    profileWith(stored),
    save === undefined ? {} : { '/profile/target-titles': save },
  )
}

function sentTitles(fetchMock: ReturnType<typeof service>): string[] {
  const [body] = sentTo(fetchMock, '/profile/target-titles') as TargetTitlesBody[]
  return body?.titles ?? []
}

// The target titles' part, where every query below looks.
function titlesPart() {
  return within(screen.getByRole('region', { name: 'Target titles' }))
}

function shownTitles(): string[] {
  const list = screen.queryByRole('list', { name: 'Your target titles' })
  if (list === null) {
    return []
  }
  return within(list)
    .getAllByRole('listitem')
    .map((item) => item.firstChild?.textContent ?? '')
}

async function loaded(): Promise<void> {
  expect(
    await screen.findByRole('textbox', { name: 'Add a target title' }),
  ).toBeInTheDocument()
}

describe('ProfilePanel', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('says it is loading, then that none are saved yet', async () => {
    const fetchMock = service([])

    render(<ProfilePanel />)

    expect(screen.getByText(LOADING)).toBeInTheDocument()
    await loaded()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(shownTitles()).toEqual([])
    const init = fetchMock.mock.calls[0]?.[1]
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${SESSION_TOKEN}`,
    )
  })

  it('lists the saved titles, each with a Remove button named for it', async () => {
    service(['Designer', 'Writer'])

    render(<ProfilePanel />)
    await loaded()

    expect(shownTitles()).toEqual(['Designer', 'Writer'])
    expect(screen.getByRole('button', { name: 'Remove Designer' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Writer' })).toBeInTheDocument()
    expect(screen.queryByText(NONE_YET)).not.toBeInTheDocument()
  })

  it('says the profile could not load, and offers nothing to save over it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('down', { status: 503 }))),
    )

    render(<ProfilePanel />)

    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says the profile could not load when Clerk has no token, asking the service nothing', async () => {
    clerk.getToken.mockResolvedValue(null)
    const fetchMock = service(['Designer'])

    render(<ProfilePanel />)

    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('says a save failed when Clerk has no token, sending nothing and keeping the list', async () => {
    const fetchMock = service(['Designer'])
    render(<ProfilePanel />)
    await loaded()
    clerk.getToken.mockResolvedValue(null)

    await userEvent.click(screen.getByRole('button', { name: 'Remove Designer' }))
    await userEvent.click(titlesPart().getByRole('button', { name: 'Save target titles' }))

    expect(await screen.findByText(NOT_SAVED)).toBeInTheDocument()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps its two status lines on the page, empty, so each message is announced', async () => {
    service(['Designer'], () => answer(200, profileWith(['Designer'])))
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    // A live region is announced when its words change, not when it arrives
    // already holding them.
    const [addLine, saveLine] = titlesPart().getAllByRole('status')
    expect(titlesPart().getAllByRole('status')).toHaveLength(2)
    expect(addLine).toHaveTextContent('')
    expect(saveLine).toHaveTextContent('')

    await user.type(
      screen.getByRole('textbox', { name: 'Add a target title' }),
      'designer{Enter}',
    )
    expect(addLine).toHaveTextContent('Designer is already in your list')
    await user.click(titlesPart().getByRole('button', { name: 'Save target titles' }))
    await screen.findByText(SAVED)
    expect(saveLine).toHaveTextContent(SAVED)
    expect(addLine).toHaveTextContent('')
  })

  it('moves focus after Remove to the next title, else the one before, else the input', async () => {
    service(['Designer', 'Writer', 'Editor'])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    screen.getByRole('button', { name: 'Remove Writer' }).focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('button', { name: 'Remove Editor' })).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(screen.getByRole('button', { name: 'Remove Designer' })).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(screen.getByRole('textbox', { name: 'Add a target title' })).toHaveFocus()
    expect(shownTitles()).toEqual([])
  })

  it('adds a trimmed title with the Add button or Enter, ignoring an empty one', async () => {
    service(['Designer'])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const input = screen.getByRole('textbox', { name: 'Add a target title' })

    await user.type(input, '  Data analyst  ')
    await user.click(titlesPart().getByRole('button', { name: 'Add target title' }))
    await user.type(input, 'Writer{Enter}')
    await user.type(input, '   {Enter}')

    expect(shownTitles()).toEqual(['Designer', 'Data analyst', 'Writer'])
    expect(input).toHaveValue('')
  })

  it('refuses a title already listed in another case, saying so', async () => {
    service(['Designer'])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    await user.type(
      screen.getByRole('textbox', { name: 'Add a target title' }),
      ' DESIGNER {Enter}',
    )

    expect(screen.getByText('Designer is already in your list')).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Designer'])
  })

  it('takes a twentieth title and refuses a twenty-first, saying so', async () => {
    const nineteen = Array.from({ length: 19 }, (_, index) => `Title ${index + 1}`)
    service(nineteen)
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const input = screen.getByRole('textbox', { name: 'Add a target title' })

    await user.type(input, 'Title 20{Enter}')
    expect(shownTitles()).toHaveLength(20)
    expect(screen.queryByText(AT_MOST_TWENTY)).not.toBeInTheDocument()

    await user.type(input, 'Title 21{Enter}')
    expect(shownTitles()).toHaveLength(20)
    expect(shownTitles()).not.toContain('Title 21')
    expect(screen.getByText(AT_MOST_TWENTY)).toBeInTheDocument()
  })

  it('takes a title of 100 characters as the server counts them and refuses 101, naming it', async () => {
    service([])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const input = screen.getByRole('textbox', { name: 'Add a target title' })
    // A hundred accented letters, each typed as a letter and a combining
    // accent, are a hundred characters once composed, as the server counts.
    const hundred = 'e\u0301'.repeat(100)
    const tooLong = 'y'.repeat(101)

    // No length limit on the input itself: it would cut a paste short unsaid.
    expect(input).not.toHaveAttribute('maxlength')
    fireEvent.change(input, { target: { value: hundred } })
    await user.type(input, '{Enter}')
    expect(shownTitles()).toEqual(['\u00e9'.repeat(100)])

    fireEvent.change(input, { target: { value: tooLong } })
    await user.type(input, '{Enter}')
    expect(shownTitles()).toEqual(['\u00e9'.repeat(100)])
    expect(
      screen.getByText(`A target title can be at most 100 characters: ${tooLong}`),
    ).toBeInTheDocument()
  })

  it('refuses a title already listed in another composed form, saying so', async () => {
    service(['Caf\u00e9 manager'])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    fireEvent.change(screen.getByRole('textbox', { name: 'Add a target title' }), {
      target: { value: 'CAFE\u0301 MANAGER' },
    })
    await user.type(screen.getByRole('textbox', { name: 'Add a target title' }), '{Enter}')

    expect(screen.getByText('Caf\u00e9 manager is already in your list')).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Caf\u00e9 manager'])
  })

  it('removes a title', async () => {
    service(['Designer', 'Writer'])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    await user.click(screen.getByRole('button', { name: 'Remove Designer' }))

    expect(shownTitles()).toEqual(['Writer'])
  })

  it('saves the whole list, held while saving, then shows Saved and the list as stored', async () => {
    let finish: (response: Response) => void = () => {}
    const fetchMock = service(
      ['Designer'],
      () => new Promise<Response>((resolve) => (finish = resolve)),
    )
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    await user.type(
      screen.getByRole('textbox', { name: 'Add a target title' }),
      'Writer{Enter}',
    )
    await user.click(titlesPart().getByRole('button', { name: 'Save target titles' }))

    expect(titlesPart().getByRole('button', { name: 'Save target titles' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByText(SAVING)).toBeInTheDocument()
    expect(sentTitles(fetchMock)).toEqual(['Designer', 'Writer'])
    const stored = profileWith(['Designer', 'Writer (stored)'])
    await act(async () => {
      finish(await answer(200, stored))
    })

    expect(await screen.findByText(SAVED)).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Designer', 'Writer (stored)'])
    expect(titlesPart().getByRole('button', { name: 'Save target titles' })).toHaveAttribute('aria-disabled', 'false')
    expect(screen.queryByText(SAVING)).not.toBeInTheDocument()
  })

  it('holds every edit and a second Save while a save is in flight', async () => {
    let finish: (response: Response) => void = () => {}
    const fetchMock = service(
      ['Designer'],
      () => new Promise<Response>((resolve) => (finish = resolve)),
    )
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const input = screen.getByRole('textbox', { name: 'Add a target title' })
    const save = titlesPart().getByRole('button', { name: 'Save target titles' })

    await user.click(save)
    for (const control of [
      input,
      titlesPart().getByRole('button', { name: 'Add target title' }),
      screen.getByRole('button', { name: 'Remove Designer' }),
      save,
    ]) {
      expect(control).toHaveAttribute('aria-disabled', 'true')
    }
    expect(input).toHaveAttribute('readonly')
    await user.type(input, 'Writer{Enter}')
    await user.click(screen.getByRole('button', { name: 'Remove Designer' }))
    await user.click(save)

    expect(shownTitles()).toEqual(['Designer'])
    expect(save).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByText(SAVING)).toBeInTheDocument()
    const saves = fetchMock.mock.calls.filter(([url]) => url === '/api/profile/target-titles')
    expect(saves).toHaveLength(1)

    await act(async () => {
      finish(await answer(200, profileWith(['Designer'])))
    })
    expect(await screen.findByText(SAVED)).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Designer'])
    expect(input).not.toHaveAttribute('readonly')
  })

  it('keeps keyboard focus on Save through a save', async () => {
    let finish: (response: Response) => void = () => {}
    service(['Designer'], () => new Promise<Response>((resolve) => (finish = resolve)))
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const save = titlesPart().getByRole('button', { name: 'Save target titles' })

    save.focus()
    await user.keyboard('{Enter}')

    // A disabled button gives up focus in a browser, so the hold must not
    // disable it.
    expect(save).not.toBeDisabled()
    expect(save).toHaveFocus()
    await act(async () => {
      finish(await answer(200, profileWith(['Designer'])))
    })
    expect(await screen.findByText(SAVED)).toBeInTheDocument()
    expect(save).toHaveFocus()
  })

  it("shows the backend's rule when it refuses the list, keeping the list", async () => {
    const refusal = {
      detail: [
        {
          loc: ['body', 'titles', 1],
          msg: 'A target title cannot contain control characters',
          type: 'target_title_control_character',
          input: 'Data\u0007analyst',
        },
      ],
    } satisfies SaveRefusalBody
    service(['Designer'], () => answer(422, refusal))
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    await user.type(
      screen.getByRole('textbox', { name: 'Add a target title' }),
      'Writer{Enter}',
    )
    await user.click(titlesPart().getByRole('button', { name: 'Save target titles' }))

    // The rule names the title by its place in the list that was sent.
    expect(
      await screen.findByText('A target title cannot contain control characters: Writer'),
    ).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Designer', 'Writer'])
    expect(screen.queryByText(SAVED)).not.toBeInTheDocument()
  })

  it('gives up on a save after five seconds without an answer, keeping the unsaved list', async () => {
    vi.useFakeTimers()
    service(['Designer'])
    render(<ProfilePanel />)
    await act(() => vi.advanceTimersByTimeAsync(0))

    fireEvent.click(screen.getByRole('button', { name: 'Remove Designer' }))
    fireEvent.click(titlesPart().getByRole('button', { name: 'Save target titles' }))
    await act(() => vi.advanceTimersByTimeAsync(4_999))
    expect(titlesPart().getByRole('button', { name: 'Save target titles' })).toHaveAttribute('aria-disabled', 'true')
    await act(() => vi.advanceTimersByTimeAsync(1))

    expect(screen.getByText(NOT_SAVED)).toBeInTheDocument()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(titlesPart().getByRole('button', { name: 'Save target titles' })).toHaveAttribute('aria-disabled', 'false')
    expect(screen.queryByText(SAVED)).not.toBeInTheDocument()
  })

  it('reaches each Remove, the input, Add and Save by Tab, in that order', async () => {
    service(['Designer', 'Writer'])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    const order = [
      screen.getByRole('button', { name: 'Remove Designer' }),
      screen.getByRole('button', { name: 'Remove Writer' }),
      screen.getByRole('textbox', { name: 'Add a target title' }),
      titlesPart().getByRole('button', { name: 'Add target title' }),
      titlesPart().getByRole('button', { name: 'Save target titles' }),
    ]
    for (const control of order) {
      await user.tab()
      expect(control).toHaveFocus()
    }
  })
})

// A part of the panel, found by its heading.
function part(heading: string) {
  return within(screen.getByRole('region', { name: heading }))
}

const NEARBY_TITLES = '/profile/title-range'

describe('ProfilePanel, as parts', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('heads the profile and each part, in order, and says what scoring reads', async () => {
    service([])
    render(<ProfilePanel />)
    await loaded()

    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Your profile')
    expect(
      screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent),
    ).toEqual([
      'Target titles',
      'Nearby titles',
      'Places',
      'Pay',
      'Skills',
      'Gaps and trade-offs',
      'Deal-breakers',
      'Companies',
      'Pace',
      'Your own rules',
    ])
    expect(
      screen.getByText('Scoring reads every section except pace, which nothing reads yet.'),
    ).toBeInTheDocument()
  })

  it('takes each part heading from the one list the interview names its saves by', async () => {
    service([])
    render(<ProfilePanel />)
    await loaded()

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent),
    ).toEqual(SAVED_SECTIONS.map((section) => SECTION_HEADINGS[section]))
  })

  it('says a part never saved is not answered yet, starting it empty, until a save lands', async () => {
    const fetchMock = service([])
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const nearby = part('Nearby titles')

    expect(nearby.getByText('Not answered yet.')).toBeInTheDocument()
    expect(part('Target titles').queryByText('Not answered yet.')).not.toBeInTheDocument()
    expect(nearby.queryByRole('list')).not.toBeInTheDocument()
    expect(nearby.getByRole('checkbox', { name: 'A lower level than my target titles is fine' })).not.toBeChecked()
    expect(part('Pay').getByRole('textbox', { name: 'Lowest base pay you would take, in US dollars a year' })).toHaveValue('')

    fetchMock.mockImplementation(() =>
      answer(200, { ...profileWith([]), title_range: { nearby_titles: [], lower_level_ok: false } }),
    )
    await user.click(nearby.getByRole('button', { name: 'Save nearby titles' }))

    expect(await nearby.findByText(SAVED)).toBeInTheDocument()
    expect(nearby.queryByText('Not answered yet.')).not.toBeInTheDocument()
    expect(part('Places').getByText('Not answered yet.')).toBeInTheDocument()
  })

  it("leaves another part's unsaved edits alone, and lets two parts save at once", async () => {
    const nearbySave = heldReply()
    const paySave = heldReply()
    const fetchMock = stubProfileService(profileWith([]), {
      [NEARBY_TITLES]: nearbySave.reply,
      '/profile/pay': paySave.reply,
    })
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const nearby = part('Nearby titles')
    const pay = part('Pay')

    await user.type(nearby.getByRole('textbox', { name: 'Add a nearby title' }), 'Data Scientist{Enter}')
    await user.type(pay.getByRole('textbox', { name: 'Lowest base pay you would take, in US dollars a year' }), '90,000')
    await user.type(pay.getByRole('textbox', { name: 'Base pay you would ask for, in US dollars a year' }), '120,000')
    await user.click(part('Places').getByRole('checkbox', { name: 'A fully remote role is fine' }))
    await user.click(nearby.getByRole('button', { name: 'Save nearby titles' }))
    await user.click(pay.getByRole('button', { name: 'Save pay' }))

    expect(sentTo(fetchMock, NEARBY_TITLES)).toHaveLength(1)
    expect(sentTo(fetchMock, '/profile/pay')).toEqual([{ floor_usd: 90_000, ask_usd: 120_000 }])
    const titleRange = { nearby_titles: ['Data Scientist'], lower_level_ok: false }
    const payStored = { floor_usd: 90_000, ask_usd: 120_000 }
    await act(async () => {
      paySave.finish(await answer(200, { ...profileWith([]), pay: payStored }))
    })
    await act(async () => {
      nearbySave.finish(
        await answer(200, { ...profileWith([]), title_range: titleRange, pay: payStored }),
      )
    })

    expect(nearby.getByText(SAVED)).toBeInTheDocument()
    expect(pay.getByText(SAVED)).toBeInTheDocument()
    expect(pay.getByRole('textbox', { name: 'Lowest base pay you would take, in US dollars a year' })).toHaveValue('90,000')
    expect(within(nearby.getByRole('list', { name: 'Your nearby titles' })).getByText('Data Scientist')).toBeInTheDocument()
    // Places was never sent: its tick is still on the page, unsaved.
    expect(part('Places').getByRole('checkbox', { name: 'A fully remote role is fine' })).toBeChecked()
    expect(part('Places').getByText('Not answered yet.')).toBeInTheDocument()
  })

  it('holds every control in a saving part, keeping focus on its Save, while the other parts stay live', async () => {
    const placesSave = heldReply()
    stubProfileService(profileWith(['Designer']), { '/profile/places': placesSave.reply })
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()
    const places = screen.getByRole('region', { name: 'Places' })
    await user.type(within(places).getByRole('textbox', { name: 'City' }), 'Boston{Enter}')
    await user.type(within(places).getByRole('textbox', { name: 'Add a company you would move for' }), 'Example Corp{Enter}')
    const save = within(places).getByRole('button', { name: 'Save places' })

    save.focus()
    await user.keyboard('{Enter}')

    expect(save).toHaveFocus()
    expect(save).not.toBeDisabled()
    const controls = [
      ...within(places).getAllByRole('textbox'),
      ...within(places).getAllByRole('button'),
      ...within(places).getAllByRole('checkbox'),
      ...within(places).getAllByRole('combobox'),
    ]
    expect(controls.length).toBeGreaterThan(55)
    for (const control of controls) {
      expect(control).toHaveAttribute('aria-disabled', 'true')
    }
    for (const heading of [
      'Target titles',
      'Nearby titles',
      'Pay',
      'Skills',
      'Gaps and trade-offs',
      'Deal-breakers',
      'Companies',
      'Pace',
      'Your own rules',
    ]) {
      const region = screen.getByRole('region', { name: heading })
      for (const control of [
        ...within(region).getAllByRole('textbox'),
        ...within(region).getAllByRole('button'),
      ]) {
        expect(control).toHaveAttribute('aria-disabled', 'false')
      }
    }
    await user.click(within(places).getByRole('checkbox', { name: 'Ohio' }))
    expect(within(places).getByRole('checkbox', { name: 'Ohio' })).not.toBeChecked()
  })

  it('aborts a save still in flight when the panel goes', async () => {
    const fetchMock = service([])
    const user = userEvent.setup()
    const { unmount } = render(<ProfilePanel />)
    await loaded()

    await user.click(part('Places').getByRole('button', { name: 'Save places' }))
    const init = fetchMock.mock.calls.find(([url]) => url === '/api/profile/places')?.[1]
    expect(init?.signal?.aborted).toBe(false)
    unmount()

    expect(init?.signal?.aborted).toBe(true)
  })
})

describe('ProfilePanel, after the interviewer saves', () => {
  const KEPT_YOURS =
    "The interviewer saved this section too. Save keeps your version; reloading the page shows the interviewer's."
  const NOT_REFRESHED =
    "Could not load the interviewer's latest saves. Reload the page to see them."
  const DEAL_BREAKERS = { industries: ['Gambling'], company_sizes: [], no_agencies: true }

  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // The profile's reads answer each body in turn, the last for every read
  // after.
  function reads(...bodies: ProfileBody[]) {
    let count = 0
    const fetchMock = stubProfileService(() => {
      count += 1
      return answer(200, bodies[Math.min(count, bodies.length) - 1] as ProfileBody)
    })
    return { fetchMock, count: () => count }
  }

  function addTitle(user: ReturnType<typeof userEvent.setup>, title: string) {
    return user.type(screen.getByRole('textbox', { name: 'Add a target title' }), `${title}{Enter}`)
  }

  function saveLine(heading: string): HTMLElement {
    const [, line] = part(heading).getAllByRole('status')
    return line as HTMLElement
  }

  it('reads the profile once for each new count, and not on its first load', async () => {
    const read = reads(profileWith(['Designer']), profileWith(['Designer', 'Writer']))
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    rerender(<ProfilePanel saves={0} />)
    expect(read.count()).toBe(1)
    // Not even begun: a second read would first ask Clerk for a token.
    expect(clerk.getToken).toHaveBeenCalledTimes(1)

    rerender(<ProfilePanel saves={1} />)

    expect(await part('Target titles').findByText('Writer')).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Designer', 'Writer'])
    expect(read.count()).toBe(2)
  })

  it('shows a section the interviewer saved in a part never answered', async () => {
    reads(profileWith(['Designer']), { ...profileWith(['Designer']), deal_breakers: DEAL_BREAKERS })
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    const dealBreakers = part('Deal-breakers')
    expect(dealBreakers.getByText('Not answered yet.')).toBeInTheDocument()

    rerender(<ProfilePanel saves={1} />)

    expect(await dealBreakers.findByText('Gambling')).toBeInTheDocument()
    expect(dealBreakers.queryByText('Not answered yet.')).not.toBeInTheDocument()
    expect(saveLine('Deal-breakers')).toHaveTextContent(/^$/)
  })

  it("keeps a part's unsaved edits over the interviewer's save, says so, and saves the person's version", async () => {
    const read = reads(profileWith(['Designer']), profileWith(['Designer', 'Analyst']))
    const fetchMock = read.fetchMock
    const user = userEvent.setup()
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    await addTitle(user, 'Writer')

    rerender(<ProfilePanel saves={1} />)

    expect(await part('Target titles').findByText(KEPT_YOURS)).toBe(saveLine('Target titles'))
    expect(shownTitles()).toEqual(['Designer', 'Writer'])
    fetchMock.mockImplementation((url: string) =>
      answer(200, profileWith(url === '/api/profile' ? ['Designer', 'Analyst'] : ['Designer', 'Writer'])),
    )
    await user.click(part('Target titles').getByRole('button', { name: 'Save target titles' }))
    expect(await part('Target titles').findByText(SAVED)).toBe(saveLine('Target titles'))
    expect(sentTitles(fetchMock)).toEqual(['Designer', 'Writer'])
  })

  it('says nothing to a part with unsaved edits whose section the interviewer left alone', async () => {
    reads(profileWith(['Designer']), { ...profileWith(['Designer']), deal_breakers: DEAL_BREAKERS })
    const user = userEvent.setup()
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    await addTitle(user, 'Writer')

    rerender(<ProfilePanel saves={1} />)

    expect(await part('Deal-breakers').findByText('Gambling')).toBeInTheDocument()
    expect(saveLine('Target titles')).toHaveTextContent(/^$/)
    expect(shownTitles()).toEqual(['Designer', 'Writer'])
  })

  it('takes the next interviewer save once the edits are saved', async () => {
    const read = reads(profileWith(['Designer']), profileWith(['Designer', 'Analyst']))
    const user = userEvent.setup()
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    await addTitle(user, 'Writer')
    read.fetchMock.mockImplementation((url: string) =>
      answer(200, profileWith(url === '/api/profile' ? ['Analyst'] : ['Designer', 'Writer'])),
    )
    await user.click(part('Target titles').getByRole('button', { name: 'Save target titles' }))
    expect(await part('Target titles').findByText(SAVED)).toBeInTheDocument()

    rerender(<ProfilePanel saves={1} />)

    expect(await part('Target titles').findByText('Analyst')).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Analyst'])
    expect(saveLine('Target titles')).toHaveTextContent(/^$/)
  })

  it('says nothing when a read brings back what the part last saved, while it holds newer edits', async () => {
    const read = reads(profileWith(['Designer']))
    const user = userEvent.setup()
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    await addTitle(user, 'Writer')
    read.fetchMock.mockImplementation((url: string) =>
      answer(200, url === '/api/profile' ? { ...profileWith(['Designer', 'Writer']), deal_breakers: DEAL_BREAKERS } : profileWith(['Designer', 'Writer'])),
    )
    await user.click(part('Target titles').getByRole('button', { name: 'Save target titles' }))
    expect(await part('Target titles').findByText(SAVED)).toBeInTheDocument()
    await addTitle(user, 'Editor')

    rerender(<ProfilePanel saves={1} />)

    expect(await part('Deal-breakers').findByText('Gambling')).toBeInTheDocument()
    expect(saveLine('Target titles')).toHaveTextContent(/^$/)
    expect(shownTitles()).toEqual(['Designer', 'Writer', 'Editor'])
  })

  it('keeps what its own save stored when the interviewer saves while it is out', async () => {
    const save = heldReply()
    let profileReads = 0
    const fetchMock = stubProfileService(
      () => {
        profileReads += 1
        return answer(200, profileWith(profileReads === 1 ? ['Designer'] : ['Designer', 'Analyst']))
      },
      { '/profile/target-titles': save.reply },
    )
    const user = userEvent.setup()
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    await addTitle(user, 'Writer')
    await user.click(part('Target titles').getByRole('button', { name: 'Save target titles' }))

    rerender(<ProfilePanel saves={1} />)
    await vi.waitFor(() => {
      expect(profileReads).toBe(2)
    })
    // Every step of the read's answer has run.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
    expect(saveLine('Target titles')).toHaveTextContent(SAVING)
    expect(shownTitles()).toEqual(['Designer', 'Writer'])
    await act(async () => {
      save.finish(new Response(JSON.stringify(profileWith(['Designer', 'Writer'])), { status: 200 }))
      await Promise.resolve()
    })

    expect(await part('Target titles').findByText(SAVED)).toBe(saveLine('Target titles'))
    expect(shownTitles()).toEqual(['Designer', 'Writer'])
    expect(sentTo(fetchMock, '/profile/target-titles')).toHaveLength(1)
  })

  it('drops an older read for a newer one', async () => {
    const first = heldReply()
    const second = heldReply()
    let count = 0
    const fetchMock = stubProfileService((init) => {
      count += 1
      return count === 1 ? answer(200, profileWith(['Designer'])) : count === 2 ? first.reply(init) : second.reply(init)
    })
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()

    rerender(<ProfilePanel saves={1} />)
    await vi.waitFor(() => {
      expect(count).toBe(2)
    })
    rerender(<ProfilePanel saves={2} />)
    await vi.waitFor(() => {
      expect(count).toBe(3)
    })

    const profileCalls = fetchMock.mock.calls.filter(([url]) => url === '/api/profile')
    expect(profileCalls[1]?.[1]?.signal?.aborted).toBe(true)
    expect(profileCalls[2]?.[1]?.signal?.aborted).toBe(false)
    await act(async () => {
      second.finish(new Response(JSON.stringify(profileWith(['Analyst'])), { status: 200 }))
      await Promise.resolve()
    })
    expect(await part('Target titles').findByText('Analyst')).toBeInTheDocument()
  })

  it('says when it could not read the latest saves, changing nothing else, until a read succeeds', async () => {
    let count = 0
    stubProfileService(() => {
      count += 1
      return count === 2
        ? Promise.resolve(new Response('down', { status: 503 }))
        : answer(200, profileWith(count === 1 ? ['Designer'] : ['Designer', 'Analyst']))
    })
    const { rerender } = render(<ProfilePanel saves={0} />)
    await loaded()
    const [panelStatus] = screen.getAllByRole('status')
    expect(panelStatus).toHaveTextContent(/^$/)

    rerender(<ProfilePanel saves={1} />)

    expect(await screen.findByText(NOT_REFRESHED)).toBe(panelStatus)
    expect(shownTitles()).toEqual(['Designer'])
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    rerender(<ProfilePanel saves={2} />)
    expect(await part('Target titles').findByText('Analyst')).toBeInTheDocument()
    expect(panelStatus).toHaveTextContent(/^$/)
  })
})
