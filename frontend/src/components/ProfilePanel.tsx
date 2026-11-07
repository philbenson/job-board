import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState } from 'react'
import {
  fetchProfile,
  saveSection,
  type ProfileRead,
  type SectionSave,
} from '../api/profile.ts'
import { withToken } from '../api/withToken.ts'
import { MAX_TARGET_TITLES, MAX_TITLE_LENGTH } from './profileLimits.ts'
import { TextListEditor } from './TextListEditor.tsx'

// One limit for each exchange, Clerk's session token included, so a token
// that never comes is no reply too. The request's own limit is as long and
// starts later, so this one is always the one that gives up.
const EXCHANGE_TIMEOUT_MS = 5_000

const NOT_SAVED = 'Could not save your target titles; your changes are still here'

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
  const [addNotice, setAddNotice] = useState<string | null>(null)
  const [save, setSave] = useState<SaveShown>({ kind: 'idle' })
  const saveController = useRef<AbortController | null>(null)
  const held = save.kind === 'saving'
  const headingId = useId()

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
        setTitles(read.profile.target_titles)
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
      (token, signal) =>
        saveSection(token, '/profile/target-titles', { titles: sent }, signal),
      'unavailable',
    ).then((saved: SectionSave<'/profile/target-titles'>) => {
      if (saved === 'aborted') {
        return
      }
      if (saved === 'unavailable') {
        setSave({ kind: 'said', message: NOT_SAVED })
      } else if (saved.kind === 'refused') {
        // A rule about one title points at its place in the list sent.
        const [field, index] = saved.at
        const title =
          field === 'titles' && typeof index === 'number' ? sent[index] : undefined
        setSave({
          kind: 'said',
          message:
            title === undefined ? saved.message : `${saved.message}: ${title}`,
        })
      } else {
        setTitles(saved.section)
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
          <TextListEditor
            items={titles}
            onChange={edit}
            onNotice={setAddNotice}
            held={held}
            inputLabel="Add a target title"
            listLabel="Your target titles"
            oneNoun="A target title"
            pluralNoun="target titles"
            cap={MAX_TARGET_TITLES}
            maxLength={MAX_TITLE_LENGTH}
            emptyText="No target titles yet"
          />
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
