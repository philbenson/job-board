import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
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
const SENDING = 'Sending your answer…'
const NOT_SENT = 'Could not send your answer. Try again.'
const LOST_TOUCH = 'Lost touch with the service; still trying'
const REPLIED = 'The interviewer replied.'
const CHANGED = 'The interview has changed since it was read; reload it and try again'
const NO_INTERVIEW = 'No interview started'
const RETRYING = 'Trying the turn again…'
const NOT_RETRIED = 'Could not try the turn again. Try again.'
const CONFIRM = 'Delete this conversation? Your profile keeps what the interview saved.'
const DELETING = 'Deleting the conversation…'
const NOT_DELETED = 'Could not delete the conversation. Try again.'

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

function answerBox(): HTMLTextAreaElement {
  return screen.getByLabelText<HTMLTextAreaElement>('Your answer')
}

function sendButton(): HTMLElement {
  return screen.getByRole('button', { name: 'Send' })
}

function showPage(state: DocumentVisibilityState): void {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(state)
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
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

    it('shows the backend sentence when the start is refused, and reads the interview it describes', async () => {
      const user = userEvent.setup()
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(
            200,
            reads === 1 ? interviewWith() : interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 1) }),
          )
        },
        start: () => interviewAnswer(409, { detail: ALREADY_STARTED }),
      })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Start the interview' }))

      expect(await screen.findByText(TAKING_TURN)).toBe(status())
      expect(alertLine()).toHaveTextContent(ALREADY_STARTED)
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      expect(screen.queryByRole('button', { name: 'Start the interview' })).toBeNull()
      expect(heading()).toHaveFocus()
    })

    it('lets a start out finish when Clerk hands the panel a new token function', async () => {
      const start = heldInterviewReply()
      stubInterviewService({ read: always(interviewWith()), start: start.reply })
      const { rerender } = render(<InterviewPanel />)
      fireEvent.click(await screen.findByRole('button', { name: 'Start the interview' }))
      await vi.waitFor(() => {
        expect(start.count()).toBe(1)
      })
      const first = clerk.getToken
      clerk.getToken = vi.fn<() => Promise<string | null>>().mockResolvedValue(SESSION_TOKEN)
      try {
        rerender(<InterviewPanel />)

        await act(() => start.finish(202, interviewWith({ status: 'running' })))

        expect(status()).toHaveTextContent(TAKING_TURN)
        expect(screen.queryByRole('button', { name: 'Start the interview' })).toBeNull()
      } finally {
        clerk.getToken = first
      }
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

  describe('answering', () => {
    const WAITING = interviewWith({
      status: 'waiting',
      question: QUESTION,
      entries: CONVERSATION,
      model_calls: 3,
    })

    it('names the question and the count as the box describes itself, counting in code points', async () => {
      stubInterviewService({ read: always(WAITING) })
      render(<InterviewPanel />)

      expect(await screen.findByLabelText('Your answer')).toHaveAccessibleDescription(
        `${QUESTION} 0 of 4,000 characters`,
      )
      fireEvent.change(answerBox(), { target: { value: '🙂'.repeat(4_000) } })

      expect(answerBox()).toHaveAccessibleDescription(`${QUESTION} 4,000 of 4,000 characters`)
      expect(sendButton()).toHaveAttribute('aria-disabled', 'false')
    })

    it('holds Send, sending nothing, while the box shows only spaces or more than 4,000 characters', async () => {
      const fetchMock = stubInterviewService({ read: always(WAITING) })
      render(<InterviewPanel />)
      await screen.findByLabelText('Your answer')

      expect(sendButton()).toHaveAttribute('aria-disabled', 'true')
      fireEvent.change(answerBox(), { target: { value: ' \n\t ' } })
      expect(sendButton()).toHaveAttribute('aria-disabled', 'true')
      fireEvent.click(sendButton())
      fireEvent.change(answerBox(), { target: { value: 'a'.repeat(4_001) } })
      expect(answerBox()).toHaveAccessibleDescription(`${QUESTION} 4,001 of 4,000 characters`)
      expect(sendButton()).toHaveAttribute('aria-disabled', 'true')
      fireEvent.click(sendButton())

      expect(callsTo(fetchMock, 'answer')).toHaveLength(0)
    })

    it('sends several lines as typed, and holds the box and Send while the answer is out, focus kept', async () => {
      const user = userEvent.setup()
      const answer = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: always(WAITING), answer: answer.reply })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer{Enter}or principal')

      await user.click(sendButton())

      const [init] = callsTo(fetchMock, 'answer')
      expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)
      expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
      expect(JSON.parse(String(init?.body))).toEqual({ text: 'Staff engineer\nor principal' })
      expect(status()).toHaveTextContent(SENDING)
      expect(sendButton()).toHaveFocus()
      expect(sendButton()).toHaveAttribute('aria-disabled', 'true')
      expect(answerBox()).toHaveAttribute('readonly')
      expect(answerBox()).toHaveAttribute('aria-disabled', 'true')
      fireEvent.change(answerBox(), { target: { value: 'something else' } })
      expect(answerBox()).toHaveValue('Staff engineer\nor principal')
      await user.click(sendButton())
      expect(answer.count()).toBe(1)
    })

    it('shows the sent answer last, holds the emptied box while the turn runs, and drops the line once the conversation holds it', async () => {
      vi.useFakeTimers()
      const read = heldInterviewReply()
      stubInterviewService({
        read: read.reply,
        answer: () =>
          interviewAnswer(202, { ...WAITING, status: 'running', question: null }),
      })
      render(<InterviewPanel />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() => read.finish(200, WAITING))
      fireEvent.change(answerBox(), { target: { value: 'Staff engineer\nor principal' } })
      sendButton().focus()

      fireEvent.click(sendButton())
      await act(() => vi.advanceTimersByTimeAsync(0))

      expect(lines().at(-1)).toBe('You (sent)Staff engineer\nor principal')
      expect(lines()).toHaveLength(CONVERSATION.length + 1)
      expect(status()).toHaveTextContent(TAKING_TURN)
      expect(answerBox()).toHaveValue('')
      expect(answerBox()).toHaveAttribute('readonly')
      expect(answerBox()).toHaveAccessibleDescription('0 of 4,000 characters')
      expect(sendButton()).toHaveFocus()

      await act(() => vi.advanceTimersByTimeAsync(2_000))
      await act(() =>
        read.finish(
          200,
          interviewWith({
            status: 'running',
            entries: [...CONVERSATION, { kind: 'person', text: 'Staff engineer\nor principal' }],
          }),
        ),
      )

      expect(lines().at(-1)).toBe('YouStaff engineer\nor principal')
      expect(lines()).toHaveLength(CONVERSATION.length + 1)
    })

    it.each([
      ['keeps focus on Send when the next question comes', 'waiting', 'Send'],
      ['hands focus to the heading when the interview ends instead', 'finished', 'heading'],
    ] as const)('%s', async (_name, ending, focused) => {
      vi.useFakeTimers()
      const read = heldInterviewReply()
      stubInterviewService({
        read: read.reply,
        answer: () => interviewAnswer(202, { ...WAITING, status: 'running', question: null }),
      })
      render(<InterviewPanel />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() => read.finish(200, WAITING))
      fireEvent.change(answerBox(), { target: { value: 'Staff engineer' } })
      sendButton().focus()
      fireEvent.click(sendButton())
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() => vi.advanceTimersByTimeAsync(2_000))

      await act(() =>
        read.finish(200, {
          ...WAITING,
          status: ending,
          question: ending === 'waiting' ? QUESTION : null,
          entries: [...CONVERSATION, { kind: 'person', text: 'Staff engineer' }],
        }),
      )

      expect(focused === 'Send' ? sendButton() : heading()).toHaveFocus()
    })

    it('drops the sent line when a read finds the turn no longer running', async () => {
      vi.useFakeTimers()
      const read = heldInterviewReply()
      stubInterviewService({
        read: read.reply,
        answer: () => interviewAnswer(202, { ...WAITING, status: 'running', question: null }),
      })
      render(<InterviewPanel />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() => read.finish(200, WAITING))
      fireEvent.change(answerBox(), { target: { value: 'Staff engineer' } })
      fireEvent.click(sendButton())
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() => vi.advanceTimersByTimeAsync(2_000))

      await act(() =>
        read.finish(200, { ...WAITING, status: 'failed', failure: 'interrupted', question: null }),
      )

      expect(lines()).toHaveLength(CONVERSATION.length)
      expect(screen.queryByText('You (sent)')).toBeNull()
    })

    it('shows the refusal while a turn runs, reads the running turn, and keeps the text for its next question', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) })
      const sentence = 'The interview is taking its turn; wait for it to finish'
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, reads === 2 ? { ...WAITING, status: 'running', question: null } : WAITING)
        },
        answer: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      expect(await screen.findByText(TAKING_TURN)).toBe(status())
      expect(alertLine()).toHaveTextContent(sentence)
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      expect(screen.queryByLabelText('Your answer')).toBeNull()
      expect(heading()).toHaveFocus()
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      expect(answerBox()).toHaveValue('Staff engineer')
    })

    it('shows the refusal when the interview no longer waits, and reads how it ended', async () => {
      const user = userEvent.setup()
      const sentence = 'The interview is not waiting on an answer'
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, reads === 1 ? WAITING : { ...WAITING, status: 'finished', question: null })
        },
        answer: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      expect(await screen.findByText(FINISHED)).toBeVisible()
      expect(alertLine()).toHaveTextContent(sentence)
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      expect(screen.queryByLabelText('Your answer')).toBeNull()
      expect(heading()).toHaveFocus()
    })

    it('reads the interview again when it changed since it was read, keeping the text under the newest question', async () => {
      const user = userEvent.setup()
      const newest = 'And which places would you work from?'
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(
            200,
            reads === 1
              ? WAITING
              : {
                  ...WAITING,
                  question: newest,
                  entries: [...CONVERSATION, { kind: 'interviewer', text: newest }],
                },
          )
        },
        answer: () => interviewAnswer(409, { detail: CHANGED }),
      })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      await vi.waitFor(() => {
        expect(lines().at(-1)).toBe(`Interviewer${newest}`)
      })
      expect(alertLine()).toHaveTextContent(CHANGED)
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      expect(answerBox()).toHaveValue('Staff engineer')
      expect(answerBox()).toHaveAccessibleDescription(`${newest} 14 of 4,000 characters`)
    })

    it('shows the first rule a refused answer broke, and keeps the text', async () => {
      const user = userEvent.setup()
      stubInterviewService({
        read: always(WAITING),
        answer: () =>
          interviewAnswer(422, {
            detail: [
              { loc: ['body', 'text'], msg: 'An answer cannot contain text direction controls', type: 'value_error' },
              { loc: ['body', 'text'], msg: 'A second rule', type: 'value_error' },
            ],
          }),
      })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      expect(await screen.findByText('An answer cannot contain text direction controls')).toBe(alertLine())
      expect(answerBox()).toHaveValue('Staff engineer')
    })

    it('says the answer did not go through when the service does not answer, and keeps the text', async () => {
      const user = userEvent.setup()
      stubInterviewService({ read: always(WAITING), answer: () => interviewAnswer(500) })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      expect(await screen.findByText(NOT_SENT)).toBe(alertLine())
      expect(answerBox()).toHaveValue('Staff engineer')
      expect(sendButton()).toHaveAttribute('aria-disabled', 'false')
    })

    it('says there is no interview when the backend has none, and reads it again', async () => {
      const user = userEvent.setup()
      let reads = 0
      stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, reads === 1 ? WAITING : interviewWith())
        },
        answer: () => interviewAnswer(404, { detail: NO_INTERVIEW }),
      })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      expect(await screen.findByRole('button', { name: 'Start the interview' })).toBeVisible()
      expect(alertLine()).toHaveTextContent(NO_INTERVIEW)
    })
  })

  describe('while a turn runs', () => {
    const RUNNING = interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 3), model_calls: 2 })

    async function mountRunning() {
      vi.useFakeTimers()
      const read = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: read.reply })
      render(<InterviewPanel />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() => read.finish(200, RUNNING))
      return { read, fetchMock }
    }

    it('reads again two seconds after each read answers, never while one is out', async () => {
      const { read } = await mountRunning()

      await act(() => vi.advanceTimersByTimeAsync(1_999))
      expect(read.count()).toBe(1)
      await act(() => vi.advanceTimersByTimeAsync(1))
      expect(read.count()).toBe(2)
      // Short of the read's own limit, after which it is a failed read.
      await act(() => vi.advanceTimersByTimeAsync(4_999))
      expect(read.count()).toBe(2)

      await act(() => read.finish(200, { ...RUNNING, model_calls: 3 }))
      expect(within(panel()).getByText('3 of 60 model calls used')).toBeVisible()
      await act(() => vi.advanceTimersByTimeAsync(1_999))
      expect(read.count()).toBe(2)
      await act(() => vi.advanceTimersByTimeAsync(1))
      expect(read.count()).toBe(3)
    })

    it('says it lost touch when a read fails, and goes on reading', async () => {
      const { read } = await mountRunning()
      await act(() => vi.advanceTimersByTimeAsync(2_000))

      await act(() => read.finish(500))

      expect(status()).toHaveTextContent(LOST_TOUCH)
      expect(lines()).toHaveLength(3)
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      expect(read.count()).toBe(3)
      await act(() => read.finish(200, RUNNING))
      expect(status()).toHaveTextContent(TAKING_TURN)
    })

    it('stops reading once the turn ends waiting on an answer, and says the interviewer replied', async () => {
      const { read } = await mountRunning()
      await act(() => vi.advanceTimersByTimeAsync(2_000))

      await act(() =>
        read.finish(200, { ...RUNNING, status: 'waiting', question: QUESTION, entries: CONVERSATION }),
      )

      expect(status()).toHaveTextContent(REPLIED)
      expect(answerBox()).toHaveAttribute('aria-disabled', 'false')
      await act(() => vi.advanceTimersByTimeAsync(60_000))
      expect(read.count()).toBe(2)
      expect(vi.getTimerCount()).toBe(0)
    })

    it('reads nothing while the page is hidden, and at once when it shows again', async () => {
      const { read } = await mountRunning()

      showPage('hidden')
      await act(() => vi.advanceTimersByTimeAsync(60_000))
      expect(read.count()).toBe(1)

      showPage('visible')
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(read.count()).toBe(2)
    })

    it('reads nothing more after a read that answers once the page is hidden', async () => {
      const { read } = await mountRunning()
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      showPage('hidden')

      await act(() => read.finish(200, RUNNING))
      await act(() => vi.advanceTimersByTimeAsync(60_000))

      expect(read.count()).toBe(2)
      expect(vi.getTimerCount()).toBe(0)
    })

    it('lets a newer read, as the page shows, abort the one in flight', async () => {
      const { read, fetchMock } = await mountRunning()
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      const [, inFlight] = callsTo(fetchMock, 'read')

      showPage('visible')
      await act(() => vi.advanceTimersByTimeAsync(0))

      expect(inFlight?.signal?.aborted).toBe(true)
      expect(read.count()).toBe(3)
    })

    it('aborts the read in flight and leaves no timer when the panel goes', async () => {
      const { fetchMock } = await mountRunning()
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      const [, inFlight] = callsTo(fetchMock, 'read')

      cleanup()

      expect(inFlight?.signal?.aborted).toBe(true)
      expect(vi.getTimerCount()).toBe(0)
    })

    it('leaves no timer when the panel goes between reads', async () => {
      await mountRunning()
      expect(vi.getTimerCount()).toBe(1)

      cleanup()

      expect(vi.getTimerCount()).toBe(0)
    })
  })

  describe('trying a failed turn again', () => {
    const FAILED = interviewWith({
      status: 'failed',
      failure: 'rate-limited',
      entries: CONVERSATION.slice(0, 3),
      model_calls: 2,
    })

    function tryAgain(): HTMLElement {
      return screen.getByRole('button', { name: 'Try again' })
    }

    it('offers Try again for every failure code', async () => {
      stubInterviewService({ read: always({ ...FAILED, failure: 'unexpected' }) })

      render(<InterviewPanel />)

      expect(await screen.findByRole('button', { name: 'Try again' })).toBeVisible()
      expect(alertLine()).toHaveTextContent("Something went wrong on the service's side.")
    })

    it('holds Try again while it runs, then shows the turn running with focus on the heading, and reads two seconds on', async () => {
      vi.useFakeTimers()
      const retry = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: always(FAILED), retry: retry.reply })
      render(<InterviewPanel />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      tryAgain().focus()

      fireEvent.click(tryAgain())
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(status()).toHaveTextContent(RETRYING)
      expect(tryAgain()).toHaveAttribute('aria-disabled', 'true')
      expect(tryAgain()).toHaveFocus()
      fireEvent.click(tryAgain())
      expect(retry.count()).toBe(1)
      const [init] = callsTo(fetchMock, 'retry')
      expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)

      await act(() => retry.finish(202, { ...FAILED, status: 'running', failure: null }))

      expect(heading()).toHaveFocus()
      expect(status()).toHaveTextContent(TAKING_TURN)
      expect(alertLine()).toHaveTextContent('')
      expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
      await act(() => vi.advanceTimersByTimeAsync(1_999))
      expect(callsTo(fetchMock, 'read')).toHaveLength(1)
      await act(() => vi.advanceTimersByTimeAsync(1))
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
    })

    it('shows the backend sentence when the retry is refused, reads again, and keeps Try again while it still failed', async () => {
      const user = userEvent.setup()
      const sentence = 'The interview needs a working Anthropic key saved first'
      const fetchMock = stubInterviewService({
        read: always(FAILED),
        retry: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Try again' }))

      expect(await screen.findByText(sentence)).toBe(alertLine())
      await vi.waitFor(() => {
        expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      })
      await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
      expect(alertLine()).toHaveTextContent(sentence)
      expect(tryAgain()).toHaveAttribute('aria-disabled', 'false')
      expect(tryAgain()).toHaveFocus()
    })

    it('shows the backend sentence when there is nothing to retry, and reads the question it waits on', async () => {
      const user = userEvent.setup()
      const sentence = 'The interview has not failed, so there is nothing to retry'
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(
            200,
            reads === 1 ? FAILED : interviewWith({ status: 'waiting', question: QUESTION, entries: CONVERSATION }),
          )
        },
        retry: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Try again' }))

      expect(await screen.findByLabelText('Your answer')).toBeVisible()
      expect(alertLine()).toHaveTextContent(sentence)
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
      expect(heading()).toHaveFocus()
    })

    it('says the retry did not go through when the service does not answer', async () => {
      const user = userEvent.setup()
      stubInterviewService({ read: always(FAILED), retry: () => interviewAnswer(500) })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Try again' }))

      expect(await screen.findByText(NOT_RETRIED)).toBe(alertLine())
      expect(tryAgain()).toHaveAttribute('aria-disabled', 'false')
    })

    it('says there is no interview when the backend has none, and reads it again', async () => {
      const user = userEvent.setup()
      let reads = 0
      stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, reads === 1 ? FAILED : interviewWith())
        },
        retry: () => interviewAnswer(404, { detail: NO_INTERVIEW }),
      })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Try again' }))

      expect(await screen.findByRole('button', { name: 'Start the interview' })).toBeVisible()
      expect(alertLine()).toHaveTextContent(NO_INTERVIEW)
    })
  })

  describe('deleting the conversation', () => {
    const FINISHED_INTERVIEW = interviewWith({
      status: 'finished',
      entries: CONVERSATION,
      model_calls: 14,
    })

    function deleteButton(): HTMLElement {
      return screen.getByRole('button', { name: 'Delete the conversation' })
    }

    function deleteIt(): HTMLElement {
      return screen.getByRole('button', { name: 'Delete it' })
    }

    function keepIt(): HTMLElement {
      return screen.getByRole('button', { name: 'Keep it' })
    }

    it.each([
      interviewWith({ status: 'waiting', question: QUESTION, entries: CONVERSATION }),
      interviewWith({ status: 'failed', failure: 'cut-off', entries: CONVERSATION }),
      FINISHED_INTERVIEW,
      interviewWith({ status: 'stopped', entries: CONVERSATION }),
    ])('offers the delete while the interview is $status', async (interview) => {
      stubInterviewService({ read: always(interview) })

      render(<InterviewPanel />)

      expect(await screen.findByRole('button', { name: 'Delete the conversation' })).toBeVisible()
    })

    it.each([interviewWith(), interviewWith({ status: 'running', entries: CONVERSATION })])(
      'offers no delete while the interview is $status',
      async (interview) => {
        stubInterviewService({ read: always(interview) })

        render(<InterviewPanel />)

        await vi.waitFor(() => {
          expect(status()).not.toHaveTextContent(LOADING)
        })
        expect(screen.queryByRole('button', { name: 'Delete the conversation' })).toBeNull()
      },
    )

    it('asks first, with focus on Keep it, and Keep it goes back with focus on the delete', async () => {
      const user = userEvent.setup()
      const fetchMock = stubInterviewService({ read: always(FINISHED_INTERVIEW) })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))

      expect(screen.getByText(CONFIRM)).toBeVisible()
      expect(keepIt()).toHaveFocus()
      expect(deleteIt()).toBeVisible()
      expect(screen.queryByRole('button', { name: 'Delete the conversation' })).toBeNull()

      await user.click(keepIt())

      expect(deleteButton()).toHaveFocus()
      expect(screen.queryByText(CONFIRM)).toBeNull()
      expect(callsTo(fetchMock, 'remove')).toHaveLength(0)
    })

    it('deletes with the token, holds Delete it while it runs, then reads as not started with focus on Start', async () => {
      const user = userEvent.setup()
      const remove = heldInterviewReply()
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, reads === 1 ? FINISHED_INTERVIEW : interviewWith())
        },
        remove: remove.reply,
      })
      render(<InterviewPanel />)
      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      expect(status()).toHaveTextContent(DELETING)
      expect(deleteIt()).toHaveAttribute('aria-disabled', 'true')
      expect(deleteIt()).toHaveFocus()
      await user.click(deleteIt())
      expect(remove.count()).toBe(1)
      const [init] = callsTo(fetchMock, 'remove')
      expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)

      await act(() => remove.finish(204))

      expect(await screen.findByText(INTRODUCTION)).toBeVisible()
      expect(startButton()).toHaveFocus()
      expect(status()).toHaveTextContent('')
      expect(within(panel()).queryByRole('list', { name: 'Conversation' })).toBeNull()
      expect(within(panel()).queryByText(/model calls used/)).toBeNull()
    })

    it('puts focus on the heading after the delete when a start still needs something', async () => {
      const user = userEvent.setup()
      let reads = 0
      stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(
            200,
            reads === 1 ? FINISHED_INTERVIEW : interviewWith({ missing: ['working-key'] }),
          )
        },
        remove: () => interviewAnswer(204),
      })
      render(<InterviewPanel />)
      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      expect(await screen.findByText(NEEDS_KEY)).toBeVisible()
      expect(heading()).toHaveFocus()
    })

    it('shows the backend sentence when the delete is refused, and reads the turn that holds it', async () => {
      const user = userEvent.setup()
      const sentence = 'The interview is taking its turn; wait for it to finish'
      const read = heldInterviewReply()
      const fetchMock = stubInterviewService({
        read: read.reply,
        remove: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)
      await vi.waitFor(() => {
        expect(read.count()).toBe(1)
      })
      await act(() => read.finish(200, FINISHED_INTERVIEW))
      await user.click(screen.getByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      expect(await screen.findByText(sentence)).toBe(alertLine())
      expect(deleteButton()).toHaveFocus()
      expect(screen.queryByText(CONFIRM)).toBeNull()
      await vi.waitFor(() => {
        expect(read.count()).toBe(2)
      })
      await act(() => read.finish(200, interviewWith({ status: 'running', entries: CONVERSATION })))
      expect(status()).toHaveTextContent(TAKING_TURN)
      expect(alertLine()).toHaveTextContent(sentence)
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      expect(screen.queryByRole('button', { name: 'Delete the conversation' })).toBeNull()
      expect(heading()).toHaveFocus()
    })

    it('says there is no interview when the backend has none, and reads it again, focus on the heading', async () => {
      const user = userEvent.setup()
      const read = heldInterviewReply()
      stubInterviewService({
        read: read.reply,
        remove: () => interviewAnswer(404, { detail: NO_INTERVIEW }),
      })
      render(<InterviewPanel />)
      await vi.waitFor(() => {
        expect(read.count()).toBe(1)
      })
      await act(() => read.finish(200, FINISHED_INTERVIEW))
      await user.click(screen.getByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      // The confirm step has closed, taking Delete it, and the read is out.
      await vi.waitFor(() => {
        expect(read.count()).toBe(2)
      })
      expect(screen.queryByText(CONFIRM)).toBeNull()
      expect(heading()).toHaveFocus()
      await act(() => read.finish(200, interviewWith()))
      expect(startButton()).toBeVisible()
      expect(alertLine()).toHaveTextContent(NO_INTERVIEW)
      expect(heading()).toHaveFocus()
    })

    it('says the delete did not go through when the service does not answer, and keeps the question open', async () => {
      const user = userEvent.setup()
      stubInterviewService({
        read: always(FINISHED_INTERVIEW),
        remove: () => interviewAnswer(500),
      })
      render(<InterviewPanel />)
      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      expect(await screen.findByText(NOT_DELETED)).toBe(alertLine())
      expect(deleteIt()).toHaveAttribute('aria-disabled', 'false')
      expect(deleteIt()).toHaveFocus()
      expect(lines()).toHaveLength(CONVERSATION.length)
    })
  })

  describe('when the page says the key or the resume changed', () => {
    it('reads again for each change, and not for a render that changes nothing', async () => {
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, interviewWith({ missing: reads === 1 ? ['working-key'] : [] }))
        },
      })
      const { rerender } = render(<InterviewPanel changes={0} />)
      expect(await screen.findByText(NEEDS_KEY)).toBeVisible()

      rerender(<InterviewPanel changes={0} />)
      expect(callsTo(fetchMock, 'read')).toHaveLength(1)
      rerender(<InterviewPanel changes={1} />)

      expect(await screen.findByText(INTRODUCTION)).toBeVisible()
      expect(screen.queryByText(NEEDS_KEY)).toBeNull()
      expect(callsTo(fetchMock, 'read')).toHaveLength(2)
    })

    it('drops the first read for the newer one when a change comes while it is out', async () => {
      const read = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: read.reply })
      const { rerender } = render(<InterviewPanel changes={0} />)
      await vi.waitFor(() => {
        expect(read.count()).toBe(1)
      })

      rerender(<InterviewPanel changes={1} />)

      await vi.waitFor(() => {
        expect(read.count()).toBe(2)
      })
      const [first, second] = callsTo(fetchMock, 'read')
      expect(first?.signal?.aborted).toBe(true)
      expect(second?.signal?.aborted).toBe(false)
      await act(() => read.finish(200, interviewWith()))
      expect(screen.getByText(INTRODUCTION)).toBeVisible()
    })

    it('shows the interview once a change reads it, after a first read that failed', async () => {
      let reads = 0
      stubInterviewService({
        read: () => {
          reads += 1
          return reads === 1 ? interviewAnswer(500) : interviewAnswer(200, interviewWith())
        },
      })
      const { rerender } = render(<InterviewPanel changes={0} />)
      expect(await screen.findByText(NOT_LOADED)).toBe(alertLine())

      rerender(<InterviewPanel changes={1} />)

      expect(await screen.findByText(INTRODUCTION)).toBeVisible()
      expect(alertLine()).toHaveTextContent('')
    })

    it('keeps what is shown when the read for a change fails', async () => {
      let reads = 0
      const fetchMock = stubInterviewService({
        read: () => {
          reads += 1
          return reads === 1 ? interviewAnswer(200, interviewWith({ missing: ['working-key'] })) : interviewAnswer(500)
        },
      })
      const { rerender } = render(<InterviewPanel changes={0} />)
      expect(await screen.findByText(NEEDS_KEY)).toBeVisible()

      rerender(<InterviewPanel changes={1} />)

      await vi.waitFor(() => {
        expect(callsTo(fetchMock, 'read')).toHaveLength(2)
      })
      await act(() => Promise.resolve())
      expect(screen.getByText(NEEDS_KEY)).toBeVisible()
      expect(alertLine()).toHaveTextContent('')
    })

    // Each request the person makes: the interview it is made on, the
    // backend's acceptance of it and what the page then shows, and a refusal
    // with the interview a read then finds.
    type Request = {
      made: string
      before: InterviewBody
      route: 'start' | 'answer' | 'retry' | 'remove'
      accepted: { status: 202; body: InterviewBody } | { status: 204 }
      make: () => void
      after: () => void
      refusal: string
      refused: InterviewBody
    }

    const TURN_RUNNING = interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 3) })

    const REQUESTS: Request[] = [
      {
        made: 'a start',
        before: interviewWith(),
        route: 'start',
        accepted: { status: 202, body: interviewWith({ status: 'running' }) },
        make: () => {
          fireEvent.click(screen.getByRole('button', { name: 'Start the interview' }))
        },
        after: () => {
          expect(status()).toHaveTextContent(TAKING_TURN)
        },
        refusal: ALREADY_STARTED,
        refused: TURN_RUNNING,
      },
      {
        made: 'an answer',
        before: interviewWith({ status: 'waiting', entries: CONVERSATION, question: QUESTION }),
        route: 'answer',
        accepted: {
          status: 202,
          body: interviewWith({
            status: 'running',
            entries: [...CONVERSATION, { kind: 'person', text: 'Staff roles' }],
          }),
        },
        make: () => {
          fireEvent.change(answerBox(), { target: { value: 'Staff roles' } })
          fireEvent.click(sendButton())
        },
        after: () => {
          expect(status()).toHaveTextContent(TAKING_TURN)
        },
        refusal: 'The interview is not waiting on an answer',
        refused: interviewWith({ status: 'finished', entries: CONVERSATION }),
      },
      {
        made: 'a retry',
        before: interviewWith({ status: 'failed', entries: CONVERSATION.slice(0, 3) }),
        route: 'retry',
        accepted: { status: 202, body: TURN_RUNNING },
        make: () => {
          fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
        },
        after: () => {
          expect(status()).toHaveTextContent(TAKING_TURN)
        },
        refusal: 'The interview has not failed, so there is nothing to retry',
        refused: interviewWith({ status: 'waiting', entries: CONVERSATION, question: QUESTION }),
      },
      {
        made: 'a delete',
        before: interviewWith({ status: 'finished', entries: CONVERSATION.slice(0, 4) }),
        route: 'remove',
        accepted: { status: 204 },
        make: () => {
          fireEvent.click(screen.getByRole('button', { name: 'Delete the conversation' }))
          fireEvent.click(screen.getByRole('button', { name: 'Delete it' }))
        },
        after: () => {
          expect(startButton()).toBeVisible()
          expect(screen.queryByText(FINISHED)).toBeNull()
        },
        refusal: 'The interview is taking its turn; wait for it to finish',
        refused: TURN_RUNNING,
      },
    ]

    // Each read held until the test answers it by its place in line.
    function heldReads() {
      const pending: ((response: Response) => void)[] = []
      return {
        reply: () =>
          new Promise<Response>((resolve) => {
            pending.push(resolve)
          }),
        count: () => pending.length,
        answer: async (index: number, body: InterviewBody) => {
          pending[index]?.(await interviewAnswer(200, body))
        },
      }
    }

    // The panel loaded with what the request is made on, its reads and the
    // request held.
    async function madeOn(request: Request) {
      const reads = heldReads()
      const held = heldInterviewReply()
      const fetchMock = stubInterviewService({ read: reads.reply, [request.route]: held.reply })
      const { rerender } = render(<InterviewPanel changes={0} />)
      await vi.waitFor(() => {
        expect(reads.count()).toBe(1)
      })
      await act(() => reads.answer(0, request.before))
      return { reads, held, fetchMock, rerender }
    }

    async function sent(held: ReturnType<typeof heldInterviewReply>): Promise<void> {
      await vi.waitFor(() => {
        expect(held.count()).toBe(1)
      })
    }

    async function accept(
      held: ReturnType<typeof heldInterviewReply>,
      accepted: Request['accepted'],
    ): Promise<void> {
      await act(() =>
        accepted.status === 204 ? held.finish(204) : held.finish(202, accepted.body),
      )
    }

    // Every answer and render the last step started has run.
    async function settled(): Promise<void> {
      await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
    }

    it.each(REQUESTS)(
      'drops the read for a change once the person sends $made, so its answer stands',
      async (request) => {
        const { reads, held, fetchMock, rerender } = await madeOn(request)
        rerender(<InterviewPanel changes={1} />)
        await vi.waitFor(() => {
          expect(reads.count()).toBe(2)
        })

        request.make()
        await sent(held)
        await accept(held, request.accepted)
        if (request.route === 'remove') {
          await vi.waitFor(() => {
            expect(reads.count()).toBe(3)
          })
          await act(() => reads.answer(2, interviewWith()))
        }
        // The read for the change answers last, with what was true before.
        await act(() => reads.answer(1, request.before))

        request.after()
        expect(callsTo(fetchMock, 'read')[1]?.signal?.aborted).toBe(true)
      },
    )

    it.each(REQUESTS)(
      'reads nothing for a change that comes while $made is out, and nothing more once it is taken',
      async (request) => {
        const { reads, held, rerender } = await madeOn(request)
        request.make()
        await sent(held)

        rerender(<InterviewPanel changes={1} />)
        await settled()
        expect(reads.count()).toBe(1)

        await accept(held, request.accepted)
        if (request.route === 'remove') {
          // The read that follows a delete is sent after it, so it is current.
          await vi.waitFor(() => {
            expect(reads.count()).toBe(2)
          })
          await act(() => reads.answer(1, interviewWith()))
        }
        await settled()
        expect(reads.count()).toBe(request.route === 'remove' ? 2 : 1)
        request.after()
      },
    )

    it.each(REQUESTS)(
      'reads once after $made fails, when a change came while it was out',
      async (request) => {
        const { reads, held, rerender } = await madeOn(request)
        request.make()
        await sent(held)
        rerender(<InterviewPanel changes={1} />)
        await settled()
        expect(reads.count()).toBe(1)

        await act(() => held.finish(500))

        await vi.waitFor(() => {
          expect(reads.count()).toBe(2)
        })
        await act(() => reads.answer(1, request.before))
        await settled()
        expect(reads.count()).toBe(2)
      },
    )

    it.each(REQUESTS)(
      'reads once after $made is refused, a change while it was out included, and keeps the sentence',
      async (request) => {
        const { reads, held, rerender } = await madeOn(request)
        request.make()
        await sent(held)
        rerender(<InterviewPanel changes={1} />)
        await settled()
        expect(reads.count()).toBe(1)

        await act(() => held.finish(409, { detail: request.refusal }))

        await vi.waitFor(() => {
          expect(reads.count()).toBe(2)
        })
        await act(() => reads.answer(1, request.refused))
        await settled()
        expect(reads.count()).toBe(2)
        expect(alertLine()).toHaveTextContent(request.refusal)
      },
    )

    it('leaves a running turn to its poll, reading nothing more for a change', async () => {
      vi.useFakeTimers()
      const read = heldInterviewReply()
      stubInterviewService({ read: read.reply })
      const { rerender } = render(<InterviewPanel changes={0} />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      await act(() =>
        read.finish(200, interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 3) })),
      )

      rerender(<InterviewPanel changes={1} />)
      await act(() => vi.advanceTimersByTimeAsync(1_999))

      expect(read.count()).toBe(1)
      await act(() => vi.advanceTimersByTimeAsync(1))
      expect(read.count()).toBe(2)
    })
  })

  describe('when the interviewer saves to the profile', () => {
    const SAVED_TITLES = { kind: 'saved', section: 'target_titles' } as const

    it('tells the page when a read holds more saved entries than the one before, not for the first read', async () => {
      vi.useFakeTimers()
      const onSaved = vi.fn()
      const read = heldInterviewReply()
      stubInterviewService({ read: read.reply })
      render(<InterviewPanel onSaved={onSaved} />)
      await act(() => vi.advanceTimersByTimeAsync(0))
      // The first read already holds one saved entry: the profile's own load is current.
      await act(() => read.finish(200, interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 4) })))
      expect(onSaved).not.toHaveBeenCalled()

      await act(() => vi.advanceTimersByTimeAsync(2_000))
      await act(() => read.finish(200, interviewWith({ status: 'running', entries: CONVERSATION.slice(0, 4) })))
      expect(onSaved).not.toHaveBeenCalled()
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      await act(() =>
        read.finish(200, interviewWith({ status: 'running', entries: [...CONVERSATION.slice(0, 4), SAVED_TITLES] })),
      )
      expect(onSaved).toHaveBeenCalledTimes(1)
      await act(() => vi.advanceTimersByTimeAsync(2_000))
      await act(() =>
        read.finish(200, interviewWith({ status: 'waiting', entries: [...CONVERSATION, SAVED_TITLES] })),
      )

      expect(onSaved).toHaveBeenCalledTimes(1)
    })

    it('tells the page of saves made after the conversation was deleted and started again', async () => {
      const onSaved = vi.fn()
      let reads = 0
      stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(
            200,
            reads === 1
              ? interviewWith({ status: 'finished', entries: CONVERSATION.slice(0, 4) })
              : reads === 2
                ? interviewWith()
                : interviewWith({ status: 'waiting', entries: [...CONVERSATION.slice(0, 1), SAVED_TITLES] }),
          )
        },
        remove: () => Promise.resolve(new Response(null, { status: 204 })),
      })
      const user = userEvent.setup()
      const { rerender } = render(<InterviewPanel onSaved={onSaved} changes={0} />)
      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))
      await user.click(screen.getByRole('button', { name: 'Delete it' }))
      expect(await screen.findByText(INTRODUCTION)).toBeVisible()

      rerender(<InterviewPanel onSaved={onSaved} changes={1} />)

      expect(await screen.findByText('Saved to your profile: Target titles')).toBeVisible()
      expect(onSaved).toHaveBeenCalledTimes(1)
    })
  })
})
