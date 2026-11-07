import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import {
  fetchProfile,
  saveTargetTitles,
  type ProfileRead,
  type TitlesSave,
} from '../api/profile.ts'
import { withToken } from '../api/withToken.ts'

// The backend holds the same cap and refuses past it; checking here too lets
// the person hear it at once, as they add, instead of when they save.
const MAX_TARGET_TITLES = 20
// The backend's longest title, in characters of the composed form; refused
// here as the title is added, rather than by the save, and not by a length
// limit on the input, which would cut a paste short without a word.
const MAX_TITLE_LENGTH = 100

// One limit for each exchange, Clerk's session token included, so a token
// that never comes is no reply too. The request's own limit is as long and
// starts later, so this one is always the one that gives up.
const EXCHANGE_TIMEOUT_MS = 5_000

const NOT_SAVED = 'Could not save your target titles; your changes are still here'

// Where focus goes after the last title is removed.
const INPUT = Symbol('the input')

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
  // After a Remove, the control that takes focus once the list has redrawn:
  // a title's Remove button, or the input.
  const focusNext = useRef<string | typeof INPUT | null>(null)
  const removeButtons = useRef(new Map<string, HTMLButtonElement>())
  const input = useRef<HTMLInputElement>(null)
  const held = save.kind === 'saving'
  const headingId = useId()
  const inputId = useId()

  useEffect(() => {
    const controller = new AbortController()
    // No token to give is no answer either.
    void withToken(
      getToken,
      EXCHANGE_TIMEOUT_MS,
      controller.signal,
      fetchProfile,
      'unavailable',
    ).then(
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

  useEffect(() => {
    const target = focusNext.current
    focusNext.current = null
    if (target === INPUT) {
      input.current?.focus()
    } else if (target !== null) {
      removeButtons.current.get(target)?.focus()
    }
  }, [titles])

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

  /**
   * Removes `title` and moves focus to the next title's Remove button, else
   * the one before, else the input, so a keyboard stays where it was working.
   */
  function remove(title: string): void {
    if (held) {
      return
    }
    const at = titles.indexOf(title)
    focusNext.current = titles[at + 1] ?? titles[at - 1] ?? INPUT
    edit(titles.filter((listed) => listed !== title))
  }

  function add(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (held) {
      return
    }
    // Composed, as the backend stores it, so a letter and its accent count
    // as one character.
    const title = draft.trim().normalize('NFC')
    if (title === '') {
      setDraft('')
      return
    }
    // Spread into code points, which is what the backend counts.
    if ([...title].length > MAX_TITLE_LENGTH) {
      setAddNotice(
        `A target title can be at most ${MAX_TITLE_LENGTH} characters: ${title}`,
      )
      return
    }
    // The backend is the authority on repeats: it folds case more fully than
    // this check ("Straße" and "STRASSE" are one title there, two here), may
    // drop a repeat this check let through, and the panel then shows its list.
    const key = repeatKey(title)
    const existing = titles.find((listed) => repeatKey(listed) === key)
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
    // The add notice was about the last Add; Save is a new act.
    setAddNotice(null)
    setSave({ kind: 'saving' })
    const sent = titles
    void withToken(
      getToken,
      EXCHANGE_TIMEOUT_MS,
      controller.signal,
      (token, signal) => saveTargetTitles(token, sent, signal),
      'unavailable',
    ).then((saved: TitlesSave) => {
      if (saved === 'aborted') {
        return
      }
      if (saved === 'unavailable') {
        setSave({ kind: 'said', message: NOT_SAVED })
      } else if (saved.kind === 'refused') {
        setSave({
          kind: 'said',
          message:
            saved.title === null
              ? saved.message
              : `${saved.message}: ${saved.title}`,
        })
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
      {loading === 'unavailable' && (
        <p role="alert">Could not load your target titles</p>
      )}
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
                    ref={(button) => {
                      if (button === null) {
                        removeButtons.current.delete(title)
                      } else {
                        removeButtons.current.set(title, button)
                      }
                    }}
                    onClick={() => {
                      remove(title)
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
              ref={input}
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
          {/* Both status lines stay on the page while the editor shows, and
              change their words, which is what a screen reader announces. */}
          <p role="status">{addNotice ?? ''}</p>
          <button type="button" aria-disabled={held} onClick={sendAll}>
            Save
          </button>
          <p role="status">
            {held ? 'Saving…' : save.kind === 'said' ? save.message : ''}
          </p>
        </>
      )}
    </section>
  )
}

function repeatKey(title: string): string {
  return title.normalize('NFC').toLowerCase()
}
