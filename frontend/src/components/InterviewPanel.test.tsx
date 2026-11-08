import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InterviewBody } from '../api/interview.ts'
import {
  callsTo,
  heldInterviewReply,
  interviewAnswer,
  interviewWith,
  stubInterviewService,
} from '../test/interviewAnswers.ts'
import { InterviewPanel } from './InterviewPanel.tsx'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const SESSION_TOKEN = 'header.payload.signature'

const LOADING = 'Loading your interview…'
const NOT_LOADED = 'Could not load your interview. Reload the page to try again.'
const INTRODUCTION =
  "The interviewer reads your resume's text, asks you one question at a time, and saves what it learns into your profile beside it. It runs on your own Anthropic key."
const NEEDS_KEY = 'Save a working Anthropic key above first'
const NEEDS_TEXT = "Check your resume's text above first"
const STARTING = 'Starting the interview…'
const TAKING_TURN = 'The interviewer is taking its turn…'
const FINISHED =
  'The interview is finished. Your profile holds what it saved, and you can edit it at any time.'
const ALREADY_STARTED = 'Your interview has already started'
const NOT_STARTED = 'Could not start the interview. Try again.'

const QUESTION = 'Which titles are you aiming for next?'

// A conversation with one line of each kind, as the backend reads it.
const CONVERSATION: InterviewBody['entries'] = [
  { kind: 'notice', text: 'The interviewer read your resume.' },
  { kind: 'interviewer', text: 'Hello. What kind of work do you want next?' },
  { kind: 'person', text: 'Platform work,\nideally on a small team.' },
  { kind: 'saved', section: 'deal_breakers' },
  { kind: 'interviewer', text: QUESTION },
]

function always(body: InterviewBody) {
  return () => interviewAnswer(200, body)
}

function panel(): HTMLElement {
  return screen.getByRole('region', { name: 'Interview' })
}

function heading(): HTMLElement {
  return screen.getByRole('heading', { level: 2, name: 'Interview' })
}

function status(): HTMLElement {
  return within(panel()).getByRole('status')
}

function alertLine(): HTMLElement {
  return within(panel()).getByRole('alert')
}

function startButton(): HTMLElement {
  return screen.getByRole('button', { name: 'Start the interview' })
}

function lines(): string[] {
  const list = within(panel()).getByRole('list', { name: 'Conversation' })
  return within(list)
    .getAllByRole('listitem')
    .map((item) => item.textContent ?? '')
}

describe('InterviewPanel', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  describe('loading', () => {
    it('mounts its status and alert lines, says it is loading, and reads with the token', async () => {
      const read = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: read.reply })

      render(<InterviewPanel />)

      expect(heading()).toHaveAttribute('tabindex', '-1')
      expect(status()).toHaveTextContent(LOADING)
      expect(alertLine()).toHaveTextContent('')
      await vi.waitFor(() => {
        expect(read.count()).toBe(1)
      })
      const [init] = callsTo(fetchMock, 'read')
      expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)

      await act(() => read.finish(200, interviewWith()))

      expect(status()).toHaveTextContent('')
      expect(screen.getByText(INTRODUCTION)).toBeVisible()
    })

    it('says the interview could not load when the service does not answer', async () => {
      stubInterviewService({ read: () => interviewAnswer(500) })

      render(<InterviewPanel />)

      expect(await screen.findByText(NOT_LOADED)).toBe(alertLine())
      expect(status()).toHaveTextContent('')
      expect(screen.queryByRole('button')).toBeNull()
    })

    it('says the interview could not load when there is no session token, and asks nothing', async () => {
      clerk.getToken.mockResolvedValue(null)
      const fetchMock = stubInterviewService({})

      render(<InterviewPanel />)

      expect(await screen.findByText(NOT_LOADED)).toBe(alertLine())
      expect(fetchMock).not.toHaveBeenCalled()
    })
  })

  describe('before a start', () => {
    it('says what the interviewer does and offers the start when nothing is missing', async () => {
      stubInterviewService({ read: always(interviewWith()) })

      render(<InterviewPanel />)

      expect(await screen.findByText(INTRODUCTION)).toBeVisible()
      expect(startButton()).toBeVisible()
      expect(within(panel()).queryByText(/model calls used/)).toBeNull()
      expect(within(panel()).queryByRole('list', { name: 'Conversation' })).toBeNull()
    })

    it('names each thing a start still needs, one line each, and offers no start', async () => {
      stubInterviewService({
        read: always(interviewWith({ missing: ['working-key', 'checked-resume-text'] })),
      })

      render(<InterviewPanel />)

      const needs = await screen.findByRole('list', { name: 'Before the interview' })
      expect(
        within(needs)
          .getAllByRole('listitem')
          .map((item) => item.textContent),
      ).toEqual([NEEDS_KEY, NEEDS_TEXT])
      expect(screen.queryByRole('button', { name: 'Start the interview' })).toBeNull()
    })

    it('names only the key when only the key is missing', async () => {
      stubInterviewService({ read: always(interviewWith({ missing: ['working-key'] })) })

      render(<InterviewPanel />)

      expect(await screen.findByText(NEEDS_KEY)).toBeVisible()
      expect(screen.queryByText(NEEDS_TEXT)).toBeNull()
    })
  })

  describe('starting', () => {
    it('starts with the token, holds Start while it runs, then shows the turn running with focus on the heading', async () => {
      const user = userEvent.setup()
      const start = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: always(interviewWith()), start: start.reply })
      render(<InterviewPanel />)
      await user.click(await screen.findByRole('button', { name: 'Start the interview' }))

      expect(startButton()).toHaveAttribute('aria-disabled', 'true')
      expect(startButton()).toHaveFocus()
      expect(status()).toHaveTextContent(STARTING)
      await user.click(startButton())
      expect(start.count()).toBe(1)
      const [init] = callsTo(fetchMock, 'start')
      expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)

      await act(() => start.finish(202, interviewWith({ status: 'running' })))

      expect(heading()).toHaveFocus()
      expect(status()).toHaveTextContent(TAKING_TURN)
      expect(screen.queryByRole('button', { name: 'Start the interview' })).toBeNull()
      expect(screen.queryByText(INTRODUCTION)).toBeNull()
      expect(within(panel()).getByText('0 of 60 model calls used')).toBeVisible()
    })

    it('shows the backend sentence when the start is refused, and keeps Start', async () => {
      const user = userEvent.setup()
      stubInterviewService({
        read: always(interviewWith()),
        start: () => interviewAnswer(409, { detail: ALREADY_STARTED }),
      })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Start the interview' }))

      expect(await screen.findByText(ALREADY_STARTED)).toBe(alertLine())
      expect(status()).toHaveTextContent('')
      expect(startButton()).toHaveAttribute('aria-disabled', 'false')
      expect(startButton()).toHaveFocus()
    })

    it('says the start did not go through when the service does not answer', async () => {
      const user = userEvent.setup()
      stubInterviewService({ read: always(interviewWith()), start: () => interviewAnswer(500) })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Start the interview' }))

      expect(await screen.findByText(NOT_STARTED)).toBe(alertLine())
      expect(startButton()).toHaveAttribute('aria-disabled', 'false')
    })
  })

  describe('the conversation', () => {
    it('names each speaker in words, and each saved section by its profile heading', async () => {
      stubInterviewService({
        read: always(interviewWith({ status: 'waiting', question: QUESTION, entries: CONVERSATION })),
      })

      render(<InterviewPanel />)

      await screen.findByRole('list', { name: 'Conversation' })
      expect(lines()).toEqual([
        'Job boardThe interviewer read your resume.',
        'InterviewerHello. What kind of work do you want next?',
        'YouPlatform work,\nideally on a small team.',
        'Saved to your profile: Deal-breakers',
        `Interviewer${QUESTION}`,
      ])
    })

    it('shows what was said as plain text with its line breaks, never as markup', async () => {
      const said = 'Line one\n<b>not bold</b>\n**not bold either**'
      const entries: InterviewBody['entries'] = [
        { kind: 'person', text: said },
        { kind: 'interviewer', text: QUESTION },
      ]
      stubInterviewService({
        read: always(interviewWith({ status: 'waiting', question: QUESTION, entries })),
      })

      render(<InterviewPanel />)

      const shown = await screen.findByText(
        (_content, element) => element?.classList.contains('said') === true && element.textContent === said,
      )
      expect(shown.childElementCount).toBe(0)
    })

    it('says the turn is running while the interviewer takes it, with no answer box', async () => {
      stubInterviewService({
        read: always(interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 3), model_calls: 2 })),
      })

      render(<InterviewPanel />)

      expect(await screen.findByText(TAKING_TURN)).toBe(status())
      expect(lines()).toHaveLength(3)
      expect(screen.queryByLabelText('Your answer')).toBeNull()
      expect(within(panel()).getByText('2 of 60 model calls used')).toBeVisible()
    })
  })

  describe('the end of the interview', () => {
    it('says the interview is finished, with the calls it used', async () => {
      stubInterviewService({
        read: always(interviewWith({ status: 'finished', entries: CONVERSATION, model_calls: 14 })),
      })

      render(<InterviewPanel />)

      expect(await screen.findByText(FINISHED)).toBeVisible()
      expect(within(panel()).getByText('14 of 60 model calls used')).toBeVisible()
      expect(lines()).toHaveLength(5)
      expect(screen.queryByLabelText('Your answer')).toBeNull()
    })

    it('says the interview reached its limit, naming the limit', async () => {
      stubInterviewService({
        read: always(
          interviewWith({ status: 'stopped', entries: CONVERSATION, model_calls: 40, model_call_limit: 40 }),
        ),
      })

      render(<InterviewPanel />)

      expect(
        await screen.findByText(
          'The interview reached its limit of 40 model calls. Your profile holds what it saved, and you can edit it at any time.',
        ),
      ).toBeVisible()
      expect(within(panel()).getByText('40 of 40 model calls used')).toBeVisible()
    })

    it('says why the last turn failed in the alert line', async () => {
      stubInterviewService({
        read: always(
          interviewWith({ status: 'failed', failure: 'no-credit', entries: CONVERSATION.slice(0, 3) }),
        ),
      })

      render(<InterviewPanel />)

      expect(await screen.findByText('Your Anthropic account is out of credit.')).toBe(alertLine())
      expect(lines()).toHaveLength(3)
      expect(screen.queryByLabelText('Your answer')).toBeNull()
    })
  })
})
