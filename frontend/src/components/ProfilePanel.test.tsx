import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  ProfileBody,
  SaveRefusalBody,
  TargetTitlesBody,
} from '../api/profile.ts'
import { ProfilePanel } from './ProfilePanel.tsx'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const SESSION_TOKEN = 'header.payload.signature'

const LOADING = 'Loading your target titles…'
const NOT_LOADED = 'Could not load your target titles'
const NONE_YET = 'No target titles yet'
const AT_MOST_TWENTY = 'You can list at most 20 target titles'
const SAVED = 'Saved'
const SAVING = 'Saving…'
const NOT_SAVED = 'Could not save your target titles; your changes are still here'

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: ProfileBody | SaveRefusalBody): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

// A request that never answers, and fails the way fetch does when aborted.
function answerOnlyAbort(init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

type Reply = (init?: RequestInit) => Promise<Response>

// The profile route answers with `stored`; the save route as the test says.
function service(stored: string[], save: Reply = () => answerOnlyAbort()) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/profile') {
      return answer(200, { target_titles: stored })
    }
    if (url === '/api/profile/target-titles') {
      return save(init)
    }
    return Promise.reject(new TypeError(`unexpected request to ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentTitles(fetchMock: ReturnType<typeof service>): string[] {
  const call = fetchMock.mock.calls.find(([url]) => url === '/api/profile/target-titles')
  const body = JSON.parse(call?.[1]?.body as string) as TargetTitlesBody
  return body.titles
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

  it('says the titles could not load, and offers nothing to save over them', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('down', { status: 503 }))),
    )

    render(<ProfilePanel />)

    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says the titles could not load when Clerk has no token, asking the service nothing', async () => {
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
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(NOT_SAVED)).toBeInTheDocument()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps its two status lines on the page, empty, so each message is announced', async () => {
    service(['Designer'], () => answer(200, { target_titles: ['Designer'] }))
    const user = userEvent.setup()
    render(<ProfilePanel />)
    await loaded()

    // A live region is announced when its words change, not when it arrives
    // already holding them.
    const [addLine, saveLine] = screen.getAllByRole('status')
    expect(screen.getAllByRole('status')).toHaveLength(2)
    expect(addLine).toHaveTextContent('')
    expect(saveLine).toHaveTextContent('')

    await user.type(
      screen.getByRole('textbox', { name: 'Add a target title' }),
      'designer{Enter}',
    )
    expect(addLine).toHaveTextContent('Designer is already in your list')
    await user.click(screen.getByRole('button', { name: 'Save' }))
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
    await user.click(screen.getByRole('button', { name: 'Add' }))
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
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByText(SAVING)).toBeInTheDocument()
    expect(sentTitles(fetchMock)).toEqual(['Designer', 'Writer'])
    const stored = { target_titles: ['Designer', 'Writer (stored)'] } satisfies ProfileBody
    await act(async () => {
      finish(await answer(200, stored))
    })

    expect(await screen.findByText(SAVED)).toBeInTheDocument()
    expect(shownTitles()).toEqual(['Designer', 'Writer (stored)'])
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'false')
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
    const save = screen.getByRole('button', { name: 'Save' })

    await user.click(save)
    for (const control of [
      input,
      screen.getByRole('button', { name: 'Add' }),
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
      finish(await answer(200, { target_titles: ['Designer'] }))
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
    const save = screen.getByRole('button', { name: 'Save' })

    save.focus()
    await user.keyboard('{Enter}')

    // A disabled button gives up focus in a browser, so the hold must not
    // disable it.
    expect(save).not.toBeDisabled()
    expect(save).toHaveFocus()
    await act(async () => {
      finish(await answer(200, { target_titles: ['Designer'] }))
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
    await user.click(screen.getByRole('button', { name: 'Save' }))

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
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await act(() => vi.advanceTimersByTimeAsync(4_999))
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'true')
    await act(() => vi.advanceTimersByTimeAsync(1))

    expect(screen.getByText(NOT_SAVED)).toBeInTheDocument()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('aria-disabled', 'false')
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
      screen.getByRole('button', { name: 'Add' }),
      screen.getByRole('button', { name: 'Save' }),
    ]
    for (const control of order) {
      await user.tab()
      expect(control).toHaveFocus()
    }
  })
})
