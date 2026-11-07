import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { askWithin } from '../api/askWithin.ts'
import {
  fetchProfile,
  saveTargetTitles,
  type ProfileRead,
  type TitlesSave,
} from '../api/profile.ts'

// The backend holds the same cap and refuses past it; checking here too lets
// the person hear it at once, as they add, instead of when they save.
const MAX_TARGET_TITLES = 20

// One limit for each exchange, Clerk's session token included, so a token
// that never comes is no reply too. The request's own limit is as long and
// starts later, so this one is always the one that gives up.
const EXCHANGE_TIMEOUT_MS = 5_000

const NOT_SAVED = 'Could not save your target titles; your changes are still here'

type GetToken = ReturnType<typeof useAuth>['getToken']

type Loading = 'loading' | 'loaded' | 'unavailable'

/** What the line under Save says; nothing until a save has been tried. */
type SaveShown =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'said'; message: string }

/**
 * The signed-in person's target titles: loads them once on mount, lets the
 * person add and remove titles, and sends the whole list on Save. The list
 * shown after a save is the backend's, which trims and drops repeats; a save
 * that fails keeps the person's unsaved list on screen.
 *
 * Invariant: what the panel shows after "Saved" is exactly what the database
 * holds, and at most one save is in flight. So the whole editor is held while
 * a save is out: nothing can change the list the answer will replace, and
 * Save cannot send a second list. The controls are held with aria-disabled
 * and guarded handlers rather than disabled, which would drop keyboard focus
 * to the page.
 */
export function ProfilePanel() {
  const { getToken } = useAuth()
  const [loading, setLoading] = useState<Loading>('loading')
  const [titles, setTitles] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [addNotice, setAddNotice] = useState<string | null>(null)
  const [save, setSave] = useState<SaveShown>({ kind: 'idle' })
  const saveController = useRef<AbortController | null>(null)
  const held = save.kind === 'saving'
  const headingId = useId()
  const inputId = useId()

  useEffect(() => {
    const controller = new AbortController()
    void withToken(getToken, controller.signal, fetchProfile).then(
      (read: ProfileRead) => {
        // An aborted load belongs to an effect that has been cleaned up; see
        // ServiceStatus for why its answer must not be shown.
        if (read === 'aborted') {
          return
        }
        if (read === 'unavailable') {
          setLoading('unavailable')
          return
        }
        setTitles(read.titles)
        setLoading('loaded')
      },
    )
    return () => {
      controller.abort()
    }
  }, [getToken])

  // A save still in flight when the panel goes has nobody to tell.
  useEffect(
    () => () => {
      saveController.current?.abort()
    },
    [],
  )

  function edit(next: string[]): void {
    if (held) {
      return
    }
    setTitles(next)
    setAddNotice(null)
    setSave({ kind: 'idle' })
  }

  function add(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (held) {
      return
    }
    const title = draft.trim()
    if (title === '') {
      setDraft('')
      return
    }
    const key = title.toLowerCase()
    const existing = titles.find((listed) => listed.toLowerCase() === key)
    if (existing !== undefined) {
      setAddNotice(`${existing} is already in your list`)
      return
    }
    if (titles.length >= MAX_TARGET_TITLES) {
      setAddNotice(`You can list at most ${MAX_TARGET_TITLES} target titles`)
      return
    }
    edit([...titles, title])
    setDraft('')
  }

  function sendAll(): void {
    if (held) {
      return
    }
    const controller = new AbortController()
    saveController.current = controller
    setSave({ kind: 'saving' })
    const sent = titles
    void withToken(getToken, controller.signal, (token, signal) =>
      saveTargetTitles(token, sent, signal),
    ).then((saved: TitlesSave) => {
      if (saved === 'aborted') {
        return
      }
      if (saved === 'unavailable') {
        setSave({ kind: 'said', message: NOT_SAVED })
      } else if (saved.kind === 'refused') {
        setSave({ kind: 'said', message: saved.message })
      } else {
        setTitles(saved.titles)
        setSave({ kind: 'said', message: 'Saved' })
      }
    })
  }

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>Target titles</h2>
      {loading === 'loading' && (
        <p role="status">Loading your target titles…</p>
      )}
      {loading === 'unavailable' && <p>Could not load your target titles</p>}
      {loading === 'loaded' && (
        <>
          {titles.length === 0 ? (
            <p>No target titles yet</p>
          ) : (
            <ul aria-label="Your target titles">
              {titles.map((title) => (
                <li key={title}>
                  <span>{title}</span>{' '}
                  <button
                    type="button"
                    aria-label={`Remove ${title}`}
                    aria-disabled={held}
                    onClick={() => {
                      edit(titles.filter((listed) => listed !== title))
                    }}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={add}>
            <label htmlFor={inputId}>Add a target title</label>{' '}
            <input
              id={inputId}
              type="text"
              value={draft}
              readOnly={held}
              aria-disabled={held}
              onChange={(event) => {
                if (!held) {
                  setDraft(event.target.value)
                }
              }}
            />{' '}
            <button type="submit" aria-disabled={held}>
              Add
            </button>
          </form>
          {addNotice !== null && <p role="status">{addNotice}</p>}
          <button type="button" aria-disabled={held} onClick={sendAll}>
            Save
          </button>
          {held && <p role="status">Saving…</p>}
          {save.kind === 'said' && <p role="status">{save.message}</p>}
        </>
      )}
    </section>
  )
}

/**
 * Asks Clerk for the session token, then runs `ask` with it, all within
 * EXCHANGE_TIMEOUT_MS. No token to give is no answer either.
 */
function withToken<T>(
  getToken: GetToken,
  signal: AbortSignal,
  ask: (token: string, signal: AbortSignal) => Promise<T>,
): Promise<T | 'unavailable' | 'aborted'> {
  return askWithin(EXCHANGE_TIMEOUT_MS, signal, async (exchangeSignal) => {
    const token = await getToken()
    if (token === null) {
      return 'unavailable'
    }
    // Past the limit or the caller's abort this signal has aborted, so a
    // token that comes late sends no request.
    return ask(token, exchangeSignal)
  })
}
