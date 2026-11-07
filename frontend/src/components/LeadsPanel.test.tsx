import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Lead, LeadsBody } from '../api/leads.ts'
import { LeadsPanel } from './LeadsPanel.tsx'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const SESSION_TOKEN = 'header.payload.signature'

const LOADING = 'Loading your leads…'
const NOT_LOADED = 'Could not load your leads.'
const NOT_REFRESHED = 'Could not refresh your leads.'
const NONE_YET =
  'No leads yet. Leads appear once your model key and at least one target title are saved and scoring next runs.'
const TITLES_AS_THEY_WERE =
  'Each lead was rated against your target titles as they were when it was scored. A change to your titles applies to postings rated after it.'
const NEWER_FIRST =
  'Newer postings are rated first; older ones follow on later runs while there is room.'

const PLATFORM_LEAD = {
  posting_id: 7,
  title: 'Platform Lead',
  company: 'Example Co',
  location: 'Remote',
  url: 'https://boards.example.com/jobs/7',
  published_at: '2026-09-01T12:00:00Z',
  score: 5,
  reason: 'Right on target.',
  scored_at: '2026-09-02T12:00:00Z',
} satisfies Lead

const STAFF_ENGINEER = {
  posting_id: 8,
  title: 'Staff Engineer',
  company: 'example-board',
  location: null,
  url: 'https://boards.example.com/jobs/8',
  published_at: null,
  score: 4,
  reason: 'A close match.',
  scored_at: '2026-09-03T12:00:00Z',
} satisfies Lead

// A body the contract allows, typed so it changes when the backend's does.
function answer(status: number, body: LeadsBody | { detail: string }): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function leads(...shown: Lead[]): Promise<Response> {
  return answer(200, { leads: shown, total: shown.length })
}

// A reply the test sends when it chooses, after reading the page meanwhile.
function laterAnswer(): {
  reply: Promise<Response>
  send: (response: Promise<Response>) => void
} {
  let send: (response: Promise<Response>) => void = () => {}
  const reply = new Promise<Response>((resolve) => {
    send = resolve
  })
  return { reply, send }
}

// The leads route answers each request with the next reply in turn.
function service(...replies: Array<(init?: RequestInit) => Promise<Response>>) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url !== '/api/leads') {
      return Promise.reject(new TypeError(`unexpected request to ${url}`))
    }
    const reply = replies.shift()
    return reply === undefined ? new Promise<Response>(() => {}) : reply(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function showPage(state: DocumentVisibilityState): void {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(state)
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

// Lets settled requests reach the component before the page is read.
async function settle(): Promise<void> {
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
}

// The date as the person's own locale writes it.
function shownDate(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
    new Date(iso),
  )
}

async function shownLeads(): Promise<HTMLElement[]> {
  const list = await screen.findByRole('list', { name: 'Your leads, best first' })
  return within(list).getAllByRole('listitem')
}

function titlesShown(items: HTMLElement[]): string[] {
  return items.map((item) => within(item).getByRole('heading', { level: 3 }).textContent ?? '')
}

describe('LeadsPanel', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('says it is loading, then lists the leads in the order the service gave', async () => {
    const fetchMock = service(() => leads(PLATFORM_LEAD, STAFF_ENGINEER))

    render(<LeadsPanel />)

    expect(screen.getByRole('heading', { level: 2, name: 'Your leads' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(LOADING)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead', 'Staff Engineer'])
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Showing the best/)).not.toBeInTheDocument()
    const init = fetchMock.mock.calls[0]?.[1]
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${SESSION_TOKEN}`,
    )
  })

  it('shows each lead as text: a link to the posting, the company and location, the score, the reason and the dates', async () => {
    service(() => leads(PLATFORM_LEAD))

    render(<LeadsPanel />)
    const [item] = await shownLeads()
    const lead = within(item as HTMLElement)

    const link = lead.getByRole('link', { name: 'Platform Lead' })
    expect(link).toHaveAttribute('href', 'https://boards.example.com/jobs/7')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(lead.getByText('Example Co · Remote')).toBeInTheDocument()
    expect(lead.getByText('5 out of 5')).toBeInTheDocument()
    expect(lead.getByText('Right on target.')).toBeInTheDocument()
    expect(
      lead.getByText(`Published ${shownDate(PLATFORM_LEAD.published_at)}`),
    ).toBeInTheDocument()
    expect(
      lead.getByText(`Rated ${shownDate(PLATFORM_LEAD.scored_at)}`),
    ).toBeInTheDocument()
  })

  it('leaves out the location and the publish date when the posting gives neither', async () => {
    service(() => leads(STAFF_ENGINEER))

    render(<LeadsPanel />)
    const [item] = await shownLeads()
    const lead = within(item as HTMLElement)

    expect(lead.getByText('example-board')).toBeInTheDocument()
    expect(lead.getByText('4 out of 5')).toBeInTheDocument()
    expect(lead.queryByText(/Published/)).not.toBeInTheDocument()
    expect(
      lead.getByText(`Rated ${shownDate(STAFF_ENGINEER.scored_at)}`),
    ).toBeInTheDocument()
  })

  it('shows markup from a posting and its rating as text, never as HTML', async () => {
    const markup = '<img src=x onerror=alert(1)>'
    service(() =>
      leads({
        ...PLATFORM_LEAD,
        title: `Title ${markup}`,
        company: `Company ${markup}`,
        location: `Location ${markup}`,
        reason: `Reason ${markup}`,
      }),
    )

    render(<LeadsPanel />)
    const [item] = await shownLeads()
    const lead = within(item as HTMLElement)

    expect((item as HTMLElement).querySelector('img')).toBeNull()
    expect(lead.getByRole('link', { name: `Title ${markup}` })).toBeInTheDocument()
    expect(lead.getByText(`Company ${markup} · Location ${markup}`)).toBeInTheDocument()
    expect(lead.getByText(`Reason ${markup}`)).toBeInTheDocument()
  })

  it.each([
    ['a script address', 'javascript:alert(1)'],
    ['a data address', 'data:text/html,<p>hello</p>'],
    ['an address that does not parse', 'boards.example.com/jobs/7'],
  ])('shows the title as plain text, not a link, for %s', async (_case, url) => {
    service(() => leads({ ...PLATFORM_LEAD, url }))

    render(<LeadsPanel />)
    const [item] = await shownLeads()
    const lead = within(item as HTMLElement)

    expect(lead.getByRole('heading', { level: 3 })).toHaveTextContent('Platform Lead')
    expect(lead.queryByRole('link')).not.toBeInTheDocument()
  })

  it('says how leads are rated only when there are leads', async () => {
    service(() => leads(PLATFORM_LEAD))

    render(<LeadsPanel />)
    await shownLeads()

    expect(screen.getByText(TITLES_AS_THEY_WERE)).toBeInTheDocument()
    expect(screen.getByText(NEWER_FIRST)).toBeInTheDocument()
  })

  it('says there are no leads yet and when to expect them, and nothing about how they are rated', async () => {
    service(() => leads())

    render(<LeadsPanel />)

    expect(await screen.findByText(NONE_YET)).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.queryByText(TITLES_AS_THEY_WERE)).not.toBeInTheDocument()
    expect(screen.queryByText(NEWER_FIRST)).not.toBeInTheDocument()
  })

  it('says how many of all the leads it shows when there are more than shown', async () => {
    service(() =>
      answer(200, { leads: [PLATFORM_LEAD, STAFF_ENGINEER], total: 140 }),
    )

    render(<LeadsPanel />)
    await shownLeads()

    expect(screen.getByText('Showing the best 2 of 140.')).toBeInTheDocument()
  })

  it('says it could not load the leads, asks again on Retry, and moves focus to the heading once it loads', async () => {
    const user = userEvent.setup()
    const retried = laterAnswer()
    service(
      () => answer(503, { detail: 'down' }),
      () => retried.reply,
    )

    render(<LeadsPanel />)

    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(screen.getByRole('status')).toHaveTextContent(LOADING)
    expect(screen.queryByText(NOT_LOADED)).not.toBeInTheDocument()
    retried.send(leads(PLATFORM_LEAD))
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    // Retry has left the page; focus goes to the heading, not to the page.
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { level: 2, name: 'Your leads' }),
    )
  })

  it('keeps Retry on the page and focused while a retry reads, held, and through a second failure', async () => {
    const user = userEvent.setup()
    const retried = laterAnswer()
    const fetchMock = service(
      () => answer(503, { detail: 'down' }),
      () => retried.reply,
    )

    render(<LeadsPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    const retry = screen.getByRole('button', { name: 'Retry' })
    await user.click(retry)
    await settle()

    expect(screen.getByRole('button', { name: 'Retry' })).toBe(retry)
    expect(retry).toHaveFocus()
    expect(retry).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('status')).toHaveTextContent(LOADING)
    expect(screen.getByRole('alert')).toBeEmptyDOMElement()
    await user.click(retry)
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(2)

    retried.send(answer(503, { detail: 'down' }))
    await settle()
    expect(screen.getByRole('alert')).toHaveTextContent(NOT_LOADED)
    expect(screen.getByRole('button', { name: 'Retry' })).toBe(retry)
    expect(retry).toHaveFocus()
    expect(retry).toHaveAttribute('aria-disabled', 'false')
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
  })

  it('keeps one status line and one alert line on the page, empty while the list is shown', async () => {
    service(() => leads(PLATFORM_LEAD))

    render(<LeadsPanel />)
    const status = screen.getByRole('status')
    const alert = screen.getByRole('alert')
    expect(status).toHaveTextContent(LOADING)
    expect(alert).toBeEmptyDOMElement()
    await shownLeads()

    expect(screen.getByRole('status')).toBe(status)
    expect(screen.getByRole('alert')).toBe(alert)
    expect(status).toBeEmptyDOMElement()
    expect(alert).toBeEmptyDOMElement()
  })

  it('keeps the list shown when a refresh fails, says so under the heading, asks again on Retry, and moves focus to the heading once it loads', async () => {
    const user = userEvent.setup()
    service(
      () => leads(PLATFORM_LEAD),
      () => answer(503, { detail: 'down' }),
      () => leads(STAFF_ENGINEER),
    )

    render(<LeadsPanel />)
    await shownLeads()
    showPage('visible')
    await settle()

    const list = screen.getByRole('list', { name: 'Your leads, best first' })
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(NOT_REFRESHED)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    expect(
      screen
        .getByRole('heading', { level: 2, name: 'Your leads' })
        .compareDocumentPosition(alert) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(alert.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await settle()

    expect(titlesShown(await shownLeads())).toEqual(['Staff Engineer'])
    expect(screen.getByRole('alert')).toBeEmptyDOMElement()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { level: 2, name: 'Your leads' }),
    )
  })

  it('moves focus to the heading when a refresh loads while Retry holds focus, unpressed', async () => {
    service(
      () => answer(503, { detail: 'down' }),
      () => leads(PLATFORM_LEAD),
    )

    render(<LeadsPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    act(() => {
      screen.getByRole('button', { name: 'Retry' }).focus()
    })
    showPage('visible')
    await settle()

    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(document.activeElement).toBe(
      screen.getByRole('heading', { level: 2, name: 'Your leads' }),
    )
  })

  it('leaves focus where it is when Retry leaves the page without holding it', async () => {
    service(
      () => answer(503, { detail: 'down' }),
      () => leads(PLATFORM_LEAD),
    )

    render(
      <>
        <button type="button">Elsewhere</button>
        <LeadsPanel />
      </>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(NOT_LOADED)
    const elsewhere = screen.getByRole('button', { name: 'Elsewhere' })
    act(() => {
      elsewhere.focus()
    })
    showPage('visible')
    await settle()

    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(elsewhere).toHaveFocus()
  })

  it('keeps the list shown while it asks again as the page comes back into view, then shows the new one, leaving focus alone', async () => {
    const refreshed = laterAnswer()
    const fetchMock = service(
      () => leads(PLATFORM_LEAD),
      () => refreshed.reply,
    )

    render(<LeadsPanel />)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    showPage('hidden')
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    showPage('visible')
    await settle()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument()
    refreshed.send(leads(STAFF_ENGINEER))
    await settle()
    expect(titlesShown(await shownLeads())).toEqual(['Staff Engineer'])
    expect(screen.getByRole('heading', { level: 2, name: 'Your leads' })).not.toHaveFocus()
  })

  it('cancels a request still out when the page comes into view again, and shows only the newest answer', async () => {
    const stale = laterAnswer()
    const newest = laterAnswer()
    const fetchMock = service(
      () => leads(PLATFORM_LEAD),
      () => stale.reply,
      () => newest.reply,
    )

    render(<LeadsPanel />)
    await shownLeads()
    showPage('visible')
    await settle()
    showPage('visible')
    await settle()

    // The cancelled request is no failure: the list stays, with nothing said.
    expect(fetchMock.mock.calls[1]?.[1]?.signal?.aborted).toBe(true)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    expect(screen.getByRole('alert')).toBeEmptyDOMElement()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    stale.send(leads(PLATFORM_LEAD))
    newest.send(leads(STAFF_ENGINEER))
    await settle()

    expect(titlesShown(await shownLeads())).toEqual(['Staff Engineer'])
  })

  it('cancels the request still out when it leaves the page', async () => {
    const fetchMock = service()

    const { unmount } = render(<LeadsPanel />)
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    unmount()

    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true)
  })
})
