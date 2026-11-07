import { useAuth } from '@clerk/react'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { askWithin } from '../api/askWithin.ts'
import {
  type ModelKeyRead,
  type ModelKeyRemoval,
  type ModelKeySave,
  readModelKey,
  removeModelKey,
  type SavedModelKeyBody,
  saveModelKey,
} from '../api/modelKey.ts'

type GetToken = ReturnType<typeof useAuth>['getToken']

// Reading and removing touch one row, so a reply slower than this is no reply.
const READ_TIMEOUT_MS = 5_000
const REMOVE_TIMEOUT_MS = 5_000
// A save waits on Anthropic's check, which the backend gives up on after 25
// seconds, so the panel waits a little longer than that.
const SAVE_TIMEOUT_MS = 30_000

const READ_FAILED = 'Could not load your model key'
const SAVE_FAILED = 'Could not save the key. Try again.'
const REMOVE_FAILED = 'Could not remove the key. Try again.'

type Saved = SavedModelKeyBody | 'none' | 'loading' | 'unreadable'

const CHECKED_DATE = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' })

/**
 * The signed-in person's own Anthropic key: whether one is saved, by its last
 * four characters only, with a form to save, replace or remove it. The key is
 * read from the input only when it is sent and is never kept in the browser:
 * not in state, not in storage, and the input is emptied once it is saved or
 * the saved key is removed.
 */
export function ModelKeyPanel() {
  const { getToken } = useAuth()
  const [saved, setSaved] = useState<Saved>('loading')
  const [replacing, setReplacing] = useState(false)
  const [busy, setBusy] = useState<'checking' | 'removing' | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const keyInput = useRef<HTMLInputElement>(null)
  // Aborted when the panel goes, so no answer lands on a panel that has gone.
  const lifetime = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    void withToken(getToken, READ_TIMEOUT_MS, controller.signal, readModelKey).then(
      (read: ModelKeyRead | 'aborted') => {
        if (read === 'aborted') {
          return
        }
        if (read === 'unavailable') {
          setSaved('unreadable')
        } else {
          setSaved(read === 'none' ? 'none' : read.saved)
        }
      },
    )
    return () => {
      controller.abort()
    }
  }, [getToken])

  const clearKeyInput = (): void => {
    if (keyInput.current !== null) {
      keyInput.current.value = ''
    }
  }

  const save = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault()
    const signal = lifetime.current?.signal
    const key = keyInput.current?.value ?? ''
    if (signal === undefined) {
      return
    }
    setBusy('checking')
    setProblem(null)
    const outcome: ModelKeySave | 'aborted' = await withToken(
      getToken,
      SAVE_TIMEOUT_MS,
      signal,
      (token, requestSignal) => saveModelKey(token, key, requestSignal),
    )
    if (outcome === 'aborted') {
      return
    }
    setBusy(null)
    if (outcome === 'unavailable') {
      setProblem(SAVE_FAILED)
    } else if ('refused' in outcome) {
      setProblem(outcome.refused)
    } else {
      clearKeyInput()
      setSaved(outcome.saved)
      setReplacing(false)
    }
  }

  const remove = async (): Promise<void> => {
    const signal = lifetime.current?.signal
    if (signal === undefined) {
      return
    }
    setBusy('removing')
    setProblem(null)
    const outcome: ModelKeyRemoval | 'aborted' = await withToken(
      getToken,
      REMOVE_TIMEOUT_MS,
      signal,
      removeModelKey,
    )
    if (outcome === 'aborted') {
      return
    }
    setBusy(null)
    if (outcome === 'unavailable') {
      setProblem(REMOVE_FAILED)
      return
    }
    clearKeyInput()
    setSaved('none')
    setReplacing(false)
  }

  return (
    <section aria-label="Model key">
      {saved === 'loading' && <p>Loading your model key…</p>}
      {saved === 'unreadable' && <p role="alert">{READ_FAILED}</p>}
      {saved === 'none' && <p>No key saved</p>}
      {typeof saved === 'object' && (
        <>
          <p>{savedLine(saved)}</p>
          {!replacing && (
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                setReplacing(true)
              }}
            >
              Replace
            </button>
          )}
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => {
              void remove()
            }}
          >
            Remove
          </button>
        </>
      )}
      {(saved === 'none' || (typeof saved === 'object' && replacing)) && (
        <form
          onSubmit={(event) => {
            void save(event)
          }}
        >
          <label>
            Anthropic API key{' '}
            <input ref={keyInput} type="password" name="key" autoComplete="off" />
          </label>{' '}
          <button type="submit" disabled={busy !== null}>
            Save
          </button>
        </form>
      )}
      {busy === 'checking' && <p role="status">Checking the key with Anthropic…</p>}
      {problem !== null && <p role="alert">{problem}</p>}
    </section>
  )
}

function savedLine(saved: SavedModelKeyBody): string {
  const checked = CHECKED_DATE.format(new Date(saved.checked_at))
  return `Anthropic key ending in ${saved.last_four}, checked ${checked}`
}

/**
 * Asks with Clerk's session token, under one time limit for the token and the
 * request together, so a token that never comes is no answer too. Without a
 * token there is nobody to ask for, which is no answer.
 */
function withToken<T>(
  getToken: GetToken,
  limitMs: number,
  signal: AbortSignal,
  ask: (token: string, signal: AbortSignal) => Promise<T>,
): Promise<T | 'unavailable' | 'aborted'> {
  return askWithin(limitMs, signal, async (askSignal) => {
    const token = await getToken()
    if (token === null) {
      return 'unavailable' as const
    }
    return ask(token, askSignal)
  })
}
