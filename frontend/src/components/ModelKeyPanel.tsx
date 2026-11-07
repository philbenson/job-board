import { useAuth } from '@clerk/react'
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import {
  type ModelKeyRead,
  type ModelKeyRemoval,
  type ModelKeySave,
  readModelKey,
  removeModelKey,
  type SavedModelKeyBody,
  saveModelKey,
} from '../api/modelKey.ts'
import { withToken } from '../api/withToken.ts'

// Reading and removing touch one row, so a reply slower than this is no reply.
const READ_TIMEOUT_MS = 5_000
const REMOVE_TIMEOUT_MS = 5_000
// A save waits on Anthropic's check, which the backend gives up on after 25
// seconds, so the panel waits a little longer than that.
const SAVE_TIMEOUT_MS = 30_000

// Without a session token there is nobody to ask for, which is no answer.
const NO_ANSWER = 'unavailable'

const READ_FAILED = 'Could not load your model key'
const SAVE_FAILED = 'Could not save the key. Try again.'
const REMOVE_FAILED = 'Could not remove the key. Try again.'

const CHECKING = 'Checking the key with Anthropic…'
const REMOVING = 'Removing the key…'
const REMOVED = 'Key removed'

type Saved = SavedModelKeyBody | 'none' | 'loading' | 'unreadable'

// Where focus goes once the next render has put it on the page.
type FocusTarget = 'input' | 'replace'

const CHECKED_DATE = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' })

/**
 * The signed-in person's own Anthropic key: whether one is saved, by its last
 * four characters only, with a form to save, replace or remove it. The key is
 * read from the input only when it is sent and is never kept in the browser:
 * not in state and not in storage. After a save the form leaves the page,
 * taking the key with it; removing the saved key empties a form that stays.
 *
 * The status and alert lines stay on the page, empty when there is nothing to
 * say, so a screen reader hears each change of their words. While a request
 * runs the buttons are held with aria-disabled rather than disabled, which
 * would drop keyboard focus to the page, and their handlers do nothing.
 */
export function ModelKeyPanel() {
  const { getToken } = useAuth()
  const [saved, setSaved] = useState<Saved>('loading')
  const [replacing, setReplacing] = useState(false)
  const [busy, setBusy] = useState<'checking' | 'removing' | null>(null)
  const [status, setStatus] = useState('')
  const [problem, setProblem] = useState('')
  const keyInput = useRef<HTMLInputElement>(null)
  const replaceButton = useRef<HTMLButtonElement>(null)
  const focusNext = useRef<FocusTarget | null>(null)
  // Aborted when the panel goes, so no answer lands on a panel that has gone.
  const lifetime = useRef<AbortController | null>(null)

  useEffect(() => {
    const target = focusNext.current
    if (target === null) {
      return
    }
    focusNext.current = null
    const element = target === 'input' ? keyInput.current : replaceButton.current
    element?.focus()
  })

  const showRead = useCallback((read: ModelKeyRead | 'aborted'): void => {
    if (read === 'aborted') {
      return
    }
    if (read === 'unavailable') {
      setSaved('unreadable')
      setProblem(READ_FAILED)
    } else {
      setSaved(read === 'none' ? 'none' : read.saved)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    void readSaved(getToken, controller.signal).then(showRead)
    return () => {
      controller.abort()
    }
  }, [getToken, showRead])

  const readAgain = (): void => {
    const signal = lifetime.current?.signal
    if (signal === undefined) {
      return
    }
    setSaved('loading')
    setProblem('')
    void readSaved(getToken, signal).then(showRead)
  }

  const save = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    const signal = lifetime.current?.signal
    const key = keyInput.current?.value ?? ''
    if (signal === undefined || busy !== null) {
      return
    }
    setBusy('checking')
    setStatus(CHECKING)
    setProblem('')
    const outcome: ModelKeySave | 'aborted' = await withToken(
      getToken,
      SAVE_TIMEOUT_MS,
      signal,
      (token, requestSignal) => saveModelKey(token, key, requestSignal),
      NO_ANSWER,
    )
    if (outcome === 'aborted') {
      return
    }
    setBusy(null)
    setStatus('')
    if (outcome === 'unavailable' || 'refused' in outcome) {
      setProblem(outcome === 'unavailable' ? SAVE_FAILED : outcome.refused)
      focusNext.current = 'input'
      return
    }
    // The form leaves the page now, and the key in its input goes with it.
    setSaved(outcome.saved)
    setReplacing(false)
  }

  const remove = async (): Promise<void> => {
    const signal = lifetime.current?.signal
    if (signal === undefined || busy !== null) {
      return
    }
    setBusy('removing')
    setStatus(REMOVING)
    setProblem('')
    const outcome: ModelKeyRemoval | 'aborted' = await withToken(
      getToken,
      REMOVE_TIMEOUT_MS,
      signal,
      removeModelKey,
      NO_ANSWER,
    )
    if (outcome === 'aborted') {
      return
    }
    setBusy(null)
    if (outcome === 'unavailable') {
      setStatus('')
      setProblem(REMOVE_FAILED)
      return
    }
    // A replace form open with a key typed in stays on the page: empty it.
    if (keyInput.current !== null) {
      keyInput.current.value = ''
    }
    setStatus(REMOVED)
    setSaved('none')
    setReplacing(false)
    focusNext.current = 'input'
  }

  const openReplace = (): void => {
    if (busy !== null) {
      return
    }
    setReplacing(true)
    setStatus('')
    focusNext.current = 'input'
  }

  const cancelReplace = (): void => {
    if (busy !== null) {
      return
    }
    setReplacing(false)
    setProblem('')
    focusNext.current = 'replace'
  }

  // A key the service can no longer open is as good as none: ask for it again.
  const usable = typeof saved === 'object' && saved.usable
  const formOpen = saved === 'none' || (typeof saved === 'object' && (replacing || !usable))
  const held = busy !== null

  return (
    <section aria-label="Model key">
      {saved === 'loading' && <p>Loading your model key…</p>}
      {saved === 'none' && <p>No key saved</p>}
      {typeof saved === 'object' && (
        <>
          <p>{savedLine(saved)}</p>
          {!formOpen && (
            <button
              ref={replaceButton}
              type="button"
              aria-disabled={held}
              onClick={openReplace}
            >
              Replace
            </button>
          )}
          <button
            type="button"
            aria-disabled={held}
            onClick={() => {
              void remove()
            }}
          >
            Remove
          </button>
        </>
      )}
      {formOpen && (
        <form
          onSubmit={(event) => {
            void save(event)
          }}
        >
          <label>
            Anthropic API key{' '}
            <input
              ref={keyInput}
              type="password"
              name="key"
              autoComplete="off"
              readOnly={busy === 'checking'}
            />
          </label>{' '}
          <button type="submit" aria-disabled={held}>
            Save
          </button>
          {usable && (
            <>
              {' '}
              <button type="button" aria-disabled={held} onClick={cancelReplace}>
                Cancel
              </button>
            </>
          )}
        </form>
      )}
      <p role="status">{status}</p>
      <p role="alert">{problem}</p>
      {saved === 'unreadable' && (
        <button type="button" onClick={readAgain}>
          Try again
        </button>
      )}
    </section>
  )
}

function readSaved(
  getToken: () => Promise<string | null>,
  signal: AbortSignal,
): Promise<ModelKeyRead | 'aborted'> {
  return withToken(getToken, READ_TIMEOUT_MS, signal, readModelKey, NO_ANSWER)
}

function savedLine(saved: SavedModelKeyBody): string {
  if (!saved.usable) {
    return `Your saved key ending in ${saved.last_four} can no longer be used. Enter it again.`
  }
  const checked = CHECKED_DATE.format(new Date(saved.checked_at))
  return `Anthropic key ending in ${saved.last_four}, checked ${checked}`
}
