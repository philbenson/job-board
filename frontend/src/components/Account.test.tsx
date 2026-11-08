import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SavedModelKeyBody } from '../api/modelKey.ts'
import type { ResumeBody } from '../api/resume.ts'
import type { ResumeTextBody } from '../api/resumeText.ts'
import {
  callsTo,
  interviewAnswer,
  interviewWith,
  stubInterviewService,
} from '../test/interviewAnswers.ts'
import { Account } from './Account.tsx'

// Clerk replaced by a stand-in whose sign-in state each test sets, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  signedIn: false,
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  ClerkLoading: () => null,
  ClerkFailed: () => null,
  Show: (props: { when: string; children: ReactNode }) =>
    (props.when === 'signed-in') === clerk.signedIn ? props.children : null,
  SignInButton: (props: { children: ReactNode }) => props.children,
  UserButton: () => <button type="button" aria-label="Open user menu" />,
  useAuth: () => ({ isLoaded: true, isSignedIn: clerk.signedIn, getToken: clerk.getToken }),
}))

const NEEDS_KEY = 'Save a working Anthropic key above first'
const NEEDS_TEXT = "Check your resume's text above first"
const UPLOADED_AT = '2026-11-07T20:29:59.747970Z'

// A body the contract allows, typed so it changes when the backend's does.
function json(status: number, body: SavedModelKeyBody | ResumeBody | ResumeTextBody): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

// The interview's read names `first` as missing until the page has told it
// of a change, and nothing after; every other route answers as `others` says
// or never.
function stubPage(
  first: 'working-key' | 'checked-resume-text',
  others: Record<string, (init?: RequestInit) => Promise<Response>>,
) {
  let reads = 0
  return stubInterviewService(
    {
      read: () => {
        reads += 1
        return interviewAnswer(200, interviewWith({ missing: reads === 1 ? [first] : [] }))
      },
    },
    (url, init) => {
      const reply = others[`${init?.method ?? 'GET'} ${url}`]
      return reply === undefined ? new Promise<Response>(() => {}) : reply(init)
    },
  )
}

describe('Account', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockReturnValue(new Promise<string | null>(() => {}))
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the target titles and the leads beside the sign-in check when signed in', () => {
    clerk.signedIn = true

    render(<Account />)

    expect(
      screen.getByRole('heading', { level: 2, name: 'Your profile' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 2, name: 'Your leads' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Confirming your sign-in with the service…'),
    ).toBeInTheDocument()
  })

  it('shows the resume, then the interview and the profile, then the leads when signed in', () => {
    clerk.signedIn = true

    render(<Account />)

    const headings = screen
      .getAllByRole('heading', { level: 2 })
      .map((heading) => heading.textContent)
    expect(headings.slice(-4)).toEqual(['Resume', 'Interview', 'Your profile', 'Your leads'])
  })

  it('holds the interview and the profile in one area, the conversation first', () => {
    clerk.signedIn = true

    render(<Account />)

    const interview = screen.getByRole('region', { name: 'Interview' })
    const area = interview.parentElement
    expect(area).toHaveClass('interview-area')
    expect(area?.firstElementChild).toBe(interview)
    expect(area?.lastElementChild).toBe(screen.getByRole('region', { name: 'Your profile' }))
  })

  it('clears the line asking for a key once a key is saved, with no reload', async () => {
    clerk.signedIn = true
    clerk.getToken.mockResolvedValue('header.payload.signature')
    const user = userEvent.setup()
    const fetchMock = stubPage('working-key', {
      'GET /api/model-key': () =>
        Promise.resolve(new Response(JSON.stringify({ detail: 'no model key saved' }), { status: 404 })),
      'PUT /api/model-key': () =>
        json(200, {
          provider: 'anthropic',
          last_four: 'wxyz',
          checked_at: '2026-11-07T12:00:00Z',
          usable: true,
          failure: null,
          failed_at: null,
        }),
    })
    render(<Account />)
    const interview = screen.getByRole('region', { name: 'Interview' })
    expect(await within(interview).findByText(NEEDS_KEY)).toBeVisible()
    await user.type(screen.getByLabelText('Anthropic API key'), 'sk-ant-api03-placeholder-wxyz')

    await user.click(within(screen.getByRole('region', { name: 'Model key' })).getByRole('button', { name: 'Save' }))

    expect(await within(interview).findByRole('button', { name: 'Start the interview' })).toBeVisible()
    expect(within(interview).queryByText(NEEDS_KEY)).toBeNull()
    expect(callsTo(fetchMock, 'read')).toHaveLength(2)
  })

  it('clears the line asking for a checked resume text once the text is saved, with no reload', async () => {
    clerk.signedIn = true
    clerk.getToken.mockResolvedValue('header.payload.signature')
    const user = userEvent.setup()
    const text = 'Avery Example\nStaff Engineer, Example Widgets'
    const fetchMock = stubPage('checked-resume-text', {
      'GET /api/resume': () => json(200, { resume: { size_bytes: 52_000, uploaded_at: UPLOADED_AT } }),
      'GET /api/resume/text': () =>
        json(200, { uploaded_at: UPLOADED_AT, state: 'found', text, checked_at: null }),
      'PUT /api/resume/text': () =>
        json(200, { uploaded_at: UPLOADED_AT, state: 'found', text, checked_at: '2026-11-07T21:00:00Z' }),
    })
    render(<Account />)
    const interview = screen.getByRole('region', { name: 'Interview' })
    expect(await within(interview).findByText(NEEDS_TEXT)).toBeVisible()
    const check = await screen.findByRole('region', { name: 'Resume text' })
    await within(check).findByLabelText("Your resume's text")

    await user.click(within(check).getByRole('button', { name: 'Save' }))

    expect(await within(interview).findByRole('button', { name: 'Start the interview' })).toBeVisible()
    expect(within(interview).queryByText(NEEDS_TEXT)).toBeNull()
    expect(callsTo(fetchMock, 'read')).toHaveLength(2)
  })

  it('shows no target titles and no leads when signed out', () => {
    clerk.signedIn = false

    render(<Account />)

    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Your profile' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Your leads' })).not.toBeInTheDocument()
  })
})
