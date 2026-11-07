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
const NONE_YET =
  'No leads yet. Postings are scored on a schedule once your model key and at least one target title are saved.'
const TITLES_AS_THEY_WERE =
  'Each lead was rated against your target titles as they were when it was scored. A change to your titles applies to postings rated after it.'
const NEWER_FIRST =
  'Newer postings are rated first; older ones follow on later runs.'

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

  it('says it could not load the leads, and asks again on Retry', async () => {
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
  })

  it('keeps the list shown while it asks again as the page comes back into view, then shows the new one', async () => {
    const refreshed = laterAnswer()
    const fetchMock = service(
      () => leads(PLATFORM_LEAD),
      () => refreshed.reply,
    )

    render(<LeadsPanel />)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    showPage('hidden')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    showPage('visible')
    await settle()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(titlesShown(await shownLeads())).toEqual(['Platform Lead'])
    expect(screen.queryByText(LOADING)).not.toBeInTheDocument()
    refreshed.send(leads(STAFF_ENGINEER))
    await settle()
    expect(titlesShown(await shownLeads())).toEqual(['Staff Engineer'])
  })

  it('cancels a request still out when the page comes into view again, and shows only the newest answer', async () => {
    const stale = laterAnswer()
    const fetchMock = service(
      () => leads(PLATFORM_LEAD),
      () => stale.reply,
      () => leads(STAFF_ENGINEER),
    )

    render(<LeadsPanel />)
    await shownLeads()
    showPage('visible')
    await settle()
    showPage('visible')
    await settle()
    stale.send(leads(PLATFORM_LEAD))
    await settle()

    expect(fetchMock.mock.calls[1]?.[1]?.signal?.aborted).toBe(true)
    expect(titlesShown(await shownLeads())).toEqual(['Staff Engineer'])
  })
})
