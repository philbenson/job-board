import { useAuth } from '@clerk/react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import {
  answerInterview,
  deleteInterview,
  fetchInterview,
  INTERVIEW_TIMEOUT_MS,
  retryInterview,
  startInterview,
  type InterviewAnswer,
  type InterviewBody,
  type InterviewRead,
  type InterviewRemoval,
  type InterviewRetry,
  type InterviewStart,
  type MissingItem,
} from '../api/interview.ts'
import { withToken } from '../api/withToken.ts'
import { AnswerBox } from './AnswerBox.tsx'
import { Conversation } from './Conversation.tsx'
import { FAILURE_SENTENCES } from './interviewFailures.ts'

// How long after a read answers the next one goes, while a turn runs.
const POLL_INTERVAL_MS = 2_000

const LOADING = 'Loading your interview…'
const NOT_LOADED = 'Could not load your interview. Reload the page to try again.'
const TAKING_TURN = 'The interviewer is taking its turn…'
const LOST_TOUCH = 'Lost touch with the service; still trying'
const REPLIED = 'The interviewer replied.'
const NOT_STARTED = 'Could not start the interview. Try again.'
const NOT_SENT = 'Could not send your answer. Try again.'
const NOT_RETRIED = 'Could not try the turn again. Try again.'
const NOT_DELETED = 'Could not delete the conversation. Try again.'
const CONFIRM = 'Delete this conversation? Your profile keeps what the interview saved.'
const NO_INTERVIEW = 'No interview started'
const KEPT = 'Your profile holds what it saved, and you can edit it at any time.'

const INTRODUCTION =
  "The interviewer reads your resume's text, asks you one question at a time, and saves what it learns into your profile beside it. It runs on your own Anthropic key."

const MISSING_LINES: Record<MissingItem, string> = {
  'working-key': 'Save a working Anthropic key above first',
  'checked-resume-text': "Check your resume's text above first",
}

// What the status line says while a request the person made is out.
type Busy = 'starting' | 'answering' | 'retrying' | 'deleting'

const BUSY_LINES: Record<Busy, string> = {
  starting: 'Starting the interview…',
  answering: 'Sending your answer…',
  retrying: 'Trying the turn again…',
  deleting: 'Deleting the conversation…',
}

type Shown =
  | { kind: 'loading' }
  | { kind: 'unreadable' }
  | { kind: 'interview'; interview: InterviewBody }

// An answer the backend took, and how many entries the interview held when it
// did; a read with more holds the answer itself.
type Sent = { text: string; after: number }

// What a request's answer leaves to read: the interview it refused or found
// gone, which is not the one shown; nothing, when the answer brings the
// interview or a read sent after it; or only a change that came meanwhile.
type Then = 'read' | 'covered' | 'read if changed'

// Where focus goes once the next render has put it on the page: a control,
// the heading, or the heading only if what held focus has left the page.
type FocusTarget = 'heading' | 'heading if lost' | 'start' | 'delete' | 'keep'

/**
 * The onboarding interview: before a start, what it does and what it still
 * needs; once started, the conversation so far, the box to answer the
 * question it waits on, how many model calls it has used, and how it ended.
 * Reads the interview on mount, and while a turn runs reads it again two
 * seconds after each read answers, one read at a time, none while the page is
 * hidden and one at once when it shows again, a newer read aborting the one
 * in flight, as the leads panel does. Every refusal and every "no interview"
 * reads it again, the backend's sentence staying in the alert line. `changes`
 * counts the page's changes to the key and the resume: each new count reads
 * the interview once more, unless a turn's poll is reading it already; one
 * that comes while a request is out waits for the request's answer, and reads
 * only if the answer brings no read of its own. `onSaved` hears when a read
 * holds more saved entries than the one before it; the first read does not
 * count, since the profile's own load is current.
 *
 * The status and alert lines stay on the page, empty when there is nothing to
 * say, so a screen reader hears each change of their words. While a request
 * runs its controls are held with aria-disabled rather than disabled, which
 * would drop keyboard focus to the page, and their handlers do nothing. A
 * control that leaves the page with focus on it hands focus to the heading.
 */
export function InterviewPanel({
  changes = 0,
  onSaved,
}: {
  changes?: number
  onSaved?: () => void
}) {
  const { getToken } = useAuth()
  const [shown, setShown] = useState<Shown>({ kind: 'loading' })
  const [busy, setBusy] = useState<Busy | null>(null)
  // A refusal or failure of the person's last request, until their next one.
  const [problem, setProblem] = useState('')
  const [text, setText] = useState('')
  const [sent, setSent] = useState<Sent | null>(null)
  // Whether the answer box stays, held, through the turn an answer started.
  const [boxKept, setBoxKept] = useState(false)
  // Whether the newest read of a running turn failed.
  const [lostTouch, setLostTouch] = useState(false)
  // Whether the poll watched the turn end waiting on the next answer.
  const [replied, setReplied] = useState(false)
  // Whether the delete is asking to be confirmed.
  const [confirming, setConfirming] = useState(false)
  const headingId = useId()
  const questionId = useId()
  const section = useRef<HTMLElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const startButton = useRef<HTMLButtonElement>(null)
  const deleteButton = useRef<HTMLButtonElement>(null)
  const keepButton = useRef<HTMLButtonElement>(null)
  const focusNext = useRef<FocusTarget | null>(null)
  // Aborted when the panel goes, so no answer lands on a panel that has gone.
  const lifetime = useRef<AbortController | null>(null)
  // A read the panel asks for once, outside the poll; a newer one aborts it.
  const readOnce = useRef<AbortController | null>(null)
  // Whether a change came while a request was out.
  const changeWaiting = useRef(false)
  // How many saved entries the last interview shown held; null before any.
  const savedCount = useRef<number | null>(null)
  // The page's latest callback, read when a save shows rather than when
  // `show` was made, so `show` stays the same for the panel's life.
  const tellSaved = useRef(onSaved)
  useEffect(() => {
    tellSaved.current = onSaved
  })

  useEffect(() => {
    const target = focusNext.current
    if (target === null) {
      return
    }
    focusNext.current = null
    if (target === 'start' || target === 'delete' || target === 'keep') {
      const controls = { start: startButton, delete: deleteButton, keep: keepButton }
      controls[target].current?.focus()
      return
    }
    const lost = !(section.current?.contains(document.activeElement) ?? false)
    if (target === 'heading' || lost) {
      heading.current?.focus()
    }
  })

  // Every interview the backend gives goes through here. `polled` says the
  // read was the poll's, which watched the turn.
  const show = useCallback((interview: InterviewBody, polled: boolean): void => {
    const running = interview.status === 'running'
    // A control holding focus may leave with the new state.
    if (
      focusNext.current === null &&
      (section.current?.contains(document.activeElement) ?? false)
    ) {
      focusNext.current = 'heading if lost'
    }
    const saved = interview.entries.filter((entry) => entry.kind === 'saved').length
    if (savedCount.current !== null && saved > savedCount.current) {
      tellSaved.current?.()
    }
    savedCount.current = saved
    setShown({ kind: 'interview', interview })
    setLostTouch(false)
    setReplied(polled && interview.status === 'waiting')
    setBoxKept((kept) => kept && running)
    // A running turn holds the interview, so it cannot be deleted.
    setConfirming((asking) => asking && !running)
    setSent((answer) =>
      answer !== null && running && interview.entries.length <= answer.after ? answer : null,
    )
  }, [])

  // Reads the interview outside the poll: first on mount, then whenever what
  // is shown is out of date. A read that fails leaves the interview shown, as
  // the alert line already says why; only a first read failing says it could
  // not load.
  const readAgain = useCallback((): void => {
    readOnce.current?.abort()
    const controller = new AbortController()
    readOnce.current = controller
    void withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      controller.signal,
      fetchInterview,
      'unavailable',
    ).then((read) => {
      // An aborted read was replaced by a newer one, or belongs to a panel
      // that has gone; see ServiceStatus for why its answer must not be shown.
      if (read === 'aborted') {
        return
      }
      if (read === 'unavailable') {
        setShown((was) => (was.kind === 'loading' ? { kind: 'unreadable' } : was))
      } else {
        show(read.interview, false)
      }
    })
  }, [getToken, show])

  // The latest readAgain, so the panel's lifetime below depends on nothing:
  // were it to end and begin again while a request was out, the request would
  // be aborted, and its handler would return with the panel still held.
  const firstRead = useRef(readAgain)
  useEffect(() => {
    firstRead.current = readAgain
  })

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    firstRead.current()
    return () => {
      controller.abort()
      readOnce.current?.abort()
    }
  }, [])

  const running = shown.kind === 'interview' && shown.interview.status === 'running'

  useEffect(() => {
    if (!running) {
      return
    }
    let controller: AbortController | undefined
    let timer: ReturnType<typeof setTimeout> | undefined

    function read(): void {
      clearTimeout(timer)
      timer = undefined
      controller?.abort()
      const current = new AbortController()
      controller = current
      void withToken(
        getToken,
        INTERVIEW_TIMEOUT_MS,
        current.signal,
        fetchInterview,
        'unavailable',
      ).then((got) => {
        // Replaced by a newer read, or the poll has stopped.
        if (got === 'aborted') {
          return
        }
        if (got === 'unavailable') {
          setLostTouch(true)
        } else {
          show(got.interview, true)
        }
        // A turn no longer running ends the poll as this effect is cleaned up.
        if (got === 'unavailable' || got.interview.status === 'running') {
          readLater()
        }
      })
    }

    function readLater(): void {
      if (document.visibilityState === 'visible') {
        timer = setTimeout(read, POLL_INTERVAL_MS)
      }
    }

    function readWhenVisible(): void {
      if (document.visibilityState === 'visible') {
        read()
      } else {
        clearTimeout(timer)
        timer = undefined
      }
    }

    readLater()
    document.addEventListener('visibilitychange', readWhenVisible)
    return () => {
      document.removeEventListener('visibilitychange', readWhenVisible)
      clearTimeout(timer)
      controller?.abort()
    }
  }, [running, getToken, show])

  // The page counts changes to the key and the resume, each of which can
  // change what the interview is missing. A running turn's poll is already
  // reading, and its last read is current.
  // A request the person makes answers with the interview as it now is, so a
  // read for a change still out would show it as it was: the request drops it
  // as it is sent, and again once its answer is in.
  function dropReadOnce(): void {
    readOnce.current?.abort()
  }

  // Once a request's answer is in, reads again what it leaves out of date. A
  // change that came while it was out reads now, after the request committed,
  // so the backend's answer to the read cannot be older than the request's.
  function settle(then: Then): void {
    dropReadOnce()
    const changed = changeWaiting.current
    changeWaiting.current = false
    if (then === 'read' || (then === 'read if changed' && changed)) {
      readAgain()
    }
  }

  const seenChanges = useRef(changes)
  useEffect(() => {
    if (changes === seenChanges.current) {
      return
    }
    seenChanges.current = changes
    if (busy !== null) {
      changeWaiting.current = true
    } else if (!running) {
      readAgain()
    }
  }, [changes, busy, running, readAgain])

  async function start(): Promise<void> {
    const signal = lifetime.current?.signal
    if (signal === undefined || busy !== null) {
      return
    }
    setBusy('starting')
    dropReadOnce()
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
    if (started === 'unavailable') {
      setProblem(NOT_STARTED)
      settle('read if changed')
      return
    }
    if (started.kind === 'conflict') {
      setProblem(started.message)
      settle('read')
      return
    }
    // Start leaves the page with the running interview, handing focus to the
    // heading; the poll reads it next.
    settle('covered')
    show(started.interview, false)
  }

  async function answer(): Promise<void> {
    const signal = lifetime.current?.signal
    if (signal === undefined || busy !== null) {
      return
    }
    const answered = text
    setBusy('answering')
    dropReadOnce()
    setProblem('')
    setReplied(false)
    const outcome: InterviewAnswer | 'aborted' = await withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      signal,
      (token, requestSignal) => answerInterview(token, answered, requestSignal),
      'unavailable',
    )
    if (outcome === 'aborted') {
      return
    }
    setBusy(null)
    if (outcome === 'unavailable') {
      setProblem(NOT_SENT)
      settle('read if changed')
    } else if (outcome === 'no interview') {
      setProblem(NO_INTERVIEW)
      settle('read')
    } else if (outcome.kind === 'conflict') {
      // The text stays in the box for the question the read brings.
      setProblem(outcome.message)
      settle('read')
    } else if (outcome.kind === 'refused') {
      setProblem(outcome.message)
      settle('read if changed')
    } else {
      settle('covered')
      // The box empties and stays, held, through the turn the answer starts,
      // so focus on it or on Send stays where it is.
      setText('')
      setBoxKept(true)
      setSent({ text: answered, after: outcome.interview.entries.length })
      show(outcome.interview, false)
    }
  }

  async function retry(): Promise<void> {
    const signal = lifetime.current?.signal
    if (signal === undefined || busy !== null) {
      return
    }
    setBusy('retrying')
    dropReadOnce()
    setProblem('')
    const retried: InterviewRetry | 'aborted' = await withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      signal,
      retryInterview,
      'unavailable',
    )
    if (retried === 'aborted') {
      return
    }
    setBusy(null)
    if (retried === 'unavailable') {
      setProblem(NOT_RETRIED)
      settle('read if changed')
    } else if (retried === 'no interview') {
      setProblem(NO_INTERVIEW)
      settle('read')
    } else if (retried.kind === 'conflict') {
      setProblem(retried.message)
      settle('read')
    } else {
      // Try again leaves the page with the running interview, handing focus to
      // the heading; the poll reads it next.
      settle('covered')
      show(retried.interview, false)
    }
  }

  async function remove(): Promise<void> {
    const signal = lifetime.current?.signal
    if (signal === undefined || busy !== null) {
      return
    }
    setBusy('deleting')
    dropReadOnce()
    setProblem('')
    const removed: InterviewRemoval | 'aborted' = await withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      signal,
      deleteInterview,
      'unavailable',
    )
    if (removed === 'aborted') {
      return
    }
    if (removed !== 'deleted') {
      setBusy(null)
      if (removed === 'unavailable') {
        // The question stays open, with focus on Delete it, to ask again.
        setProblem(NOT_DELETED)
        settle('read if changed')
        return
      }
      setConfirming(false)
      if (removed === 'no interview') {
        // Delete it leaves the page with the confirm step, and the read for
        // the interview is still out.
        focusNext.current = 'heading'
        setProblem(NO_INTERVIEW)
      } else {
        focusNext.current = 'delete'
        setProblem(removed.message)
      }
      settle('read')
      return
    }
    // The read below is sent after the delete, so it covers any change so far.
    settle('covered')
    // The 204 carries no body, and what a start still needs is only the
    // backend's to say, so the panel reads the interview, not-started now.
    const read: InterviewRead | 'aborted' = await withToken(
      getToken,
      INTERVIEW_TIMEOUT_MS,
      signal,
      fetchInterview,
      'unavailable',
    )
    if (read === 'aborted') {
      return
    }
    setBusy(null)
    setConfirming(false)
    setText('')
    settle('read if changed')
    if (read === 'unavailable') {
      focusNext.current = 'heading'
      setShown({ kind: 'unreadable' })
      return
    }
    focusNext.current = read.interview.missing.length === 0 ? 'start' : 'heading'
    show(read.interview, false)
  }

  const interview = shown.kind === 'interview' ? shown.interview : null
  const status = interview?.status ?? null

  let statusLine = ''
  if (busy !== null) {
    statusLine = BUSY_LINES[busy]
  } else if (shown.kind === 'loading') {
    statusLine = LOADING
  } else if (status === 'running') {
    statusLine = lostTouch ? LOST_TOUCH : TAKING_TURN
  } else if (replied) {
    statusLine = REPLIED
  }

  let alertLine = problem
  if (alertLine === '' && shown.kind === 'unreadable') {
    alertLine = NOT_LOADED
  } else if (alertLine === '' && interview?.status === 'failed') {
    // The backend names a failed turn's cause; without one, it is its own.
    alertLine = FAILURE_SENTENCES[interview.failure ?? 'unexpected']
  }

  const boxShown = status === 'waiting' || (status === 'running' && boxKept)

  return (
    <section ref={section} aria-labelledby={headingId} className="interview">
      <h2 id={headingId} ref={heading} tabIndex={-1}>
        Interview
      </h2>
      <p role="status">{statusLine}</p>
      {interview?.status === 'not-started' &&
        (interview.missing.length === 0 ? (
          <>
            <p>{INTRODUCTION}</p>
            <button
              ref={startButton}
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
          <Conversation
            entries={interview.entries}
            sent={sent?.text ?? null}
            questionId={questionId}
          />
          {interview.status === 'finished' && <p>{`The interview is finished. ${KEPT}`}</p>}
          {interview.status === 'stopped' && (
            <p>{`The interview reached its limit of ${interview.model_call_limit} model calls. ${KEPT}`}</p>
          )}
        </>
      )}
      {boxShown && (
        <AnswerBox
          text={text}
          onText={setText}
          held={busy !== null || status !== 'waiting'}
          questionId={interview?.question == null ? null : questionId}
          onSend={() => {
            void answer()
          }}
        />
      )}
      <p role="alert">{alertLine}</p>
      {status === 'failed' && (
        <button
          type="button"
          aria-disabled={busy !== null}
          onClick={() => {
            void retry()
          }}
        >
          Try again
        </button>
      )}
      {interview !== null && interview.status !== 'not-started' && (
        <p>{`${interview.model_calls} of ${interview.model_call_limit} model calls used`}</p>
      )}
      {interview !== null &&
        interview.status !== 'not-started' &&
        interview.status !== 'running' &&
        (confirming ? (
          <div className="confirm">
            <p>{CONFIRM}</p>
            <button
              type="button"
              aria-disabled={busy !== null}
              onClick={() => {
                void remove()
              }}
            >
              Delete it
            </button>
            <button
              ref={keepButton}
              type="button"
              aria-disabled={busy !== null}
              onClick={() => {
                if (busy === null) {
                  focusNext.current = 'delete'
                  setConfirming(false)
                }
              }}
            >
              Keep it
            </button>
          </div>
        ) : (
          <button
            ref={deleteButton}
            type="button"
            aria-disabled={busy !== null}
            onClick={() => {
              if (busy === null) {
                focusNext.current = 'keep'
                setProblem('')
                setConfirming(true)
              }
            }}
          >
            Delete the conversation
          </button>
        ))}
    </section>
  )
}
