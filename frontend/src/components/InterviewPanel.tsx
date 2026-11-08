import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState } from 'react'
import {
  fetchInterview,
  INTERVIEW_TIMEOUT_MS,
  startInterview,
  type InterviewBody,
  type InterviewStart,
  type MissingItem,
} from '../api/interview.ts'
import { withToken } from '../api/withToken.ts'
import { Conversation } from './Conversation.tsx'
import { FAILURE_SENTENCES } from './interviewFailures.ts'

const LOADING = 'Loading your interview…'
const NOT_LOADED = 'Could not load your interview. Reload the page to try again.'
const TAKING_TURN = 'The interviewer is taking its turn…'
const NOT_STARTED = 'Could not start the interview. Try again.'
const KEPT = 'Your profile holds what it saved, and you can edit it at any time.'

const INTRODUCTION =
  "The interviewer reads your resume's text, asks you one question at a time, and saves what it learns into your profile beside it. It runs on your own Anthropic key."

const MISSING_LINES: Record<MissingItem, string> = {
  'working-key': 'Save a working Anthropic key above first',
  'checked-resume-text': "Check your resume's text above first",
}

// What the status line says while a request the person made is out.
type Busy = 'starting'

const BUSY_LINES: Record<Busy, string> = {
  starting: 'Starting the interview…',
}

type Shown =
  | { kind: 'loading' }
  | { kind: 'unreadable' }
  | { kind: 'interview'; interview: InterviewBody }

// Where focus goes once the next render has put it on the page.
type FocusTarget = 'heading'

/**
 * The onboarding interview: before a start, what it does and what it still
 * needs; once started, the conversation so far, how many model calls it has
 * used, and how it ended. Reads the interview once on mount.
 *
 * The status and alert lines stay on the page, empty when there is nothing to
 * say, so a screen reader hears each change of their words. While a request
 * runs its button is held with aria-disabled rather than disabled, which
 * would drop keyboard focus to the page, and its handler does nothing.
 */
export function InterviewPanel() {
  const { getToken } = useAuth()
  const [shown, setShown] = useState<Shown>({ kind: 'loading' })
  const [busy, setBusy] = useState<Busy | null>(null)
  // A refusal or failure of the person's last request, until their next one.
  const [problem, setProblem] = useState('')
  const headingId = useId()
  const questionId = useId()
  const heading = useRef<HTMLHeadingElement>(null)
  const focusNext = useRef<FocusTarget | null>(null)
  // Aborted when the panel goes, so no answer lands on a panel that has gone.
  const lifetime = useRef<AbortController | null>(null)

  useEffect(() => {
    const target = focusNext.current
    if (target === null) {
      return
    }
    focusNext.current = null
    heading.current?.focus()
  })

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    void withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      controller.signal,
      fetchInterview,
      'unavailable',
    ).then((read) => {
      // An aborted read belongs to an effect that has been cleaned up; see
      // ServiceStatus for why its answer must not be shown.
      if (read === 'aborted') {
        return
      }
      setShown(
        read === 'unavailable'
          ? { kind: 'unreadable' }
          : { kind: 'interview', interview: read.interview },
      )
    })
    return () => {
      controller.abort()
    }
  }, [getToken])

  async function start(): Promise<void> {
    const signal = lifetime.current?.signal
    if (signal === undefined || busy !== null) {
      return
    }
    setBusy('starting')
    setProblem('')
    const started: InterviewStart | 'aborted' = await withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      signal,
      startInterview,
      'unavailable',
    )
    if (started === 'aborted') {
      return
    }
    setBusy(null)
    if (started === 'unavailable' || started.kind === 'conflict') {
      setProblem(started === 'unavailable' ? NOT_STARTED : started.message)
      return
    }
    // Start leaves the page with the running interview; the heading stays.
    focusNext.current = 'heading'
    setShown({ kind: 'interview', interview: started.interview })
  }

  const interview = shown.kind === 'interview' ? shown.interview : null
  const status = interview?.status ?? null

  let statusLine = ''
  if (busy !== null) {
    statusLine = BUSY_LINES[busy]
  } else if (shown.kind === 'loading') {
    statusLine = LOADING
  } else if (status === 'running') {
    statusLine = TAKING_TURN
  }

  let alertLine = problem
  if (alertLine === '' && shown.kind === 'unreadable') {
    alertLine = NOT_LOADED
  } else if (alertLine === '' && interview?.status === 'failed') {
    // The backend names a failed turn's cause; without one, it is its own.
    alertLine = FAILURE_SENTENCES[interview.failure ?? 'unexpected']
  }

  return (
    <section aria-labelledby={headingId} className="interview">
      <h2 id={headingId} ref={heading} tabIndex={-1}>
        Interview
      </h2>
      <p role="status">{statusLine}</p>
      {interview?.status === 'not-started' &&
        (interview.missing.length === 0 ? (
          <>
            <p>{INTRODUCTION}</p>
            <button
              type="button"
              aria-disabled={busy !== null}
              onClick={() => {
                void start()
              }}
            >
              Start the interview
            </button>
          </>
        ) : (
          <ul aria-label="Before the interview">
            {interview.missing.map((item) => (
              <li key={item}>{MISSING_LINES[item]}</li>
            ))}
          </ul>
        ))}
      {interview !== null && interview.status !== 'not-started' && (
        <>
          <Conversation entries={interview.entries} sent={null} questionId={questionId} />
          {interview.status === 'finished' && <p>{`The interview is finished. ${KEPT}`}</p>}
          {interview.status === 'stopped' && (
            <p>{`The interview reached its limit of ${interview.model_call_limit} model calls. ${KEPT}`}</p>
          )}
        </>
      )}
      <p role="alert">{alertLine}</p>
      {interview !== null && interview.status !== 'not-started' && (
        <p>{`${interview.model_calls} of ${interview.model_call_limit} model calls used`}</p>
      )}
    </section>
  )
}
