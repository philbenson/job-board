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

    it.each([
      'The interview is taking its turn; wait for it to finish',
      'The interview is not waiting on an answer',
    ])('shows the refusal "%s" and keeps the text', async (sentence) => {
      const user = userEvent.setup()
      const fetchMock = stubInterviewService({
        read: always(WAITING),
        answer: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)
      await user.type(await screen.findByLabelText('Your answer'), 'Staff engineer')

      await user.click(sendButton())

      expect(await screen.findByText(sentence)).toBe(alertLine())
      expect(answerBox()).toHaveValue('Staff engineer')
      expect(sendButton()).toHaveAttribute('aria-disabled', 'false')
      expect(callsTo(fetchMock, 'read')).toHaveLength(1)
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

    it('shows the backend sentence when the retry is refused, and keeps Try again', async () => {
      const user = userEvent.setup()
      const sentence = 'The interview needs a working Anthropic key saved first'
      stubInterviewService({
        read: always(FAILED),
        retry: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)

      await user.click(await screen.findByRole('button', { name: 'Try again' }))

      expect(await screen.findByText(sentence)).toBe(alertLine())
      expect(tryAgain()).toHaveAttribute('aria-disabled', 'false')
      expect(tryAgain()).toHaveFocus()
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

    it('shows the backend sentence when the delete is refused, with focus back on the delete', async () => {
      const user = userEvent.setup()
      const sentence = 'The interview is taking its turn; wait for it to finish'
      stubInterviewService({
        read: always(FINISHED_INTERVIEW),
        remove: () => interviewAnswer(409, { detail: sentence }),
      })
      render(<InterviewPanel />)
      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      expect(await screen.findByText(sentence)).toBe(alertLine())
      expect(deleteButton()).toHaveFocus()
      expect(screen.queryByText(CONFIRM)).toBeNull()
    })

    it('says there is no interview when the backend has none, and reads it again', async () => {
      const user = userEvent.setup()
      let reads = 0
      stubInterviewService({
        read: () => {
          reads += 1
          return interviewAnswer(200, reads === 1 ? FINISHED_INTERVIEW : interviewWith())
        },
        remove: () => interviewAnswer(404, { detail: NO_INTERVIEW }),
      })
      render(<InterviewPanel />)
      await user.click(await screen.findByRole('button', { name: 'Delete the conversation' }))

      await user.click(deleteIt())

      expect(await screen.findByRole('button', { name: 'Start the interview' })).toBeVisible()
      expect(alertLine()).toHaveTextContent(NO_INTERVIEW)
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
})
