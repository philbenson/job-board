import { useAuth } from '@clerk/react'
import { useEffect, useRef, useState } from 'react'
import {
  saveSection,
  type SectionBody,
  type SectionRoute,
  type SectionSave,
  type StoredSection,
} from '../api/profile.ts'
import { withToken } from '../api/withToken.ts'
import { refusalSentence, type Named } from './profileRefusals.ts'

// One limit for each exchange, Clerk's session token included, so a token
// that never comes is no reply too. The request's own limit is as long and
// starts later, so this one is always the one that gives up.
export const EXCHANGE_TIMEOUT_MS = 5_000

/** The save line's words when the interviewer saved a section being edited. */
export const KEPT_YOURS =
  "The interviewer saved this section too. Save keeps your version; reloading the page shows the interviewer's."

/**
 * The profile panel's reads after its first: `version` numbers the read the
 * stored sections came from, counted when it was sent, and `newestSent` the
 * newest read sent so far.
 */
export type ProfileReads = { version: number; newestSent: () => number }

/** What the line under Save says; nothing until a save has been tried. */
type SaveShown =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'said'; message: string }

/** One part's save, its two lines, and whether it has been answered. */
export type ProfilePart<Route extends SectionRoute> = {
  /** A save is out: every control in the part changes nothing. */
  held: boolean
  /** False until the section is first saved, by any visit. */
  answered: boolean
  /** The editors' notice line. */
  notice: string
  /** The save's line. */
  saveLine: string
  /** Puts a notice on the editors' line, as an editor refuses an edit. */
  say: (notice: string) => void
  /**
   * Applies an edit, unless held; an edit makes both lines out of date, so
   * it clears them.
   */
  edit: (apply: () => void) => void
  /**
   * Sends `body` whole, unless held. `named` says what a refusal pointing
   * into the body names; the section the backend answers goes to `take`.
   */
  send: (body: SectionBody<Route>, named: Named<SectionBody<Route>>) => void
}

/**
 * The save of one section, kept apart from every other part's: its own
 * request, aborted when the part goes, and its own lines. `stored` is the
 * section as the profile panel last read it, and `reads` numbers the panel's
 * reads after its first, which happen when the interviewer saves.
 * `take` shows a stored section in the part's editors: the one a save
 * answers, or one a later read brings, which it takes while rendering, so a
 * part declares the state `take` sets before it calls this hook.
 *
 * Invariant: what the part shows after "Saved" is what the database holds
 * for its section, and at most one of its saves is in flight. So the part
 * is held while a save is out: nothing can change what the answer will
 * replace, and Save cannot send a second body. No later read shows a section
 * older than the part's own last save: a read sent before that save answered
 * may have been served before it committed, so the part takes only reads
 * sent after. Nor does a read replace what the person has typed: a part with
 * unsaved edits keeps them and says the interviewer saved the section too.
 */
export function useProfilePart<Route extends SectionRoute>(
  route: Route,
  stored: StoredSection<Route> | null,
  notSaved: string,
  reads: ProfileReads,
  take: (section: StoredSection<Route>) => void,
): ProfilePart<Route> {
  const { getToken } = useAuth()
  const [answered, setAnswered] = useState(stored !== null)
  const [notice, setNotice] = useState('')
  const [save, setSave] = useState<SaveShown>({ kind: 'idle' })
  // Edits made since the part last took a stored section.
  const [unsaved, setUnsaved] = useState(false)
  const controller = useRef<AbortController | null>(null)
  // The section as the part last heard it stored, by any read or save, so a
  // read that brings it unchanged changes nothing.
  const [known, setKnown] = useState(stored)
  const [seenVersion, setSeenVersion] = useState(reads.version)
  // The newest read sent when the part's own save last answered; 0, the
  // first load, before any save.
  const [savedAfter, setSavedAfter] = useState(0)
  const held = save.kind === 'saving'

  // A newer read of the profile, taken in render as a prop change is, so the
  // part never shows the old section beside the new version.
  if (reads.version !== seenVersion) {
    setSeenVersion(reads.version)
    // A save out answers with what it stored, which the part then shows. So
    // the read is dropped here, and a section the interviewer saved just
    // after that save landed is not shown until the next read or a reload.
    if (!held && reads.version > savedAfter && stored !== null && !sameSection(stored, known)) {
      setKnown(stored)
      setAnswered(true)
      if (unsaved) {
        setSave({ kind: 'said', message: KEPT_YOURS })
      } else {
        take(stored)
        // Both lines spoke of what the part showed before.
        setNotice('')
        setSave({ kind: 'idle' })
      }
    }
  }

  // A save still in flight when the part goes has nobody to tell.
  useEffect(
    () => () => {
      controller.current?.abort()
    },
    [],
  )

  function edit(apply: () => void): void {
    if (held) {
      return
    }
    apply()
    setUnsaved(true)
    setNotice('')
    setSave({ kind: 'idle' })
  }

  function send(body: SectionBody<Route>, named: Named<SectionBody<Route>>): void {
    if (held) {
      return
    }
    const ask = new AbortController()
    controller.current = ask
    // The notice was about the last edit; Save is a new act.
    setNotice('')
    setSave({ kind: 'saving' })
    void withToken(
      getToken,
      EXCHANGE_TIMEOUT_MS,
      ask.signal,
      (token, signal) => saveSection(token, route, body, signal),
      'unavailable',
    ).then((saved: SectionSave<Route>) => {
      if (saved === 'aborted') {
        return
      }
      if (saved === 'unavailable') {
        setSave({ kind: 'said', message: notSaved })
      } else if (saved.kind === 'refused') {
        setSave({
          kind: 'said',
          message: refusalSentence(saved.message, saved.at, named),
        })
      } else {
        setKnown(saved.section)
        setSavedAfter(reads.newestSent())
        take(saved.section)
        setUnsaved(false)
        setAnswered(true)
        setSave({ kind: 'said', message: 'Saved' })
      }
    })
  }

  return {
    held,
    answered,
    notice,
    saveLine: held ? 'Saving…' : save.kind === 'said' ? save.message : '',
    say: setNotice,
    edit,
    send,
  }
}

// Two reads of one section, each as the backend wrote it, so the same
// section is the same text.
function sameSection(one: unknown, other: unknown): boolean {
  return JSON.stringify(one) === JSON.stringify(other)
}
