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
   * into the body names; `stored` is given the section the backend answers.
   */
  send: (
    body: SectionBody<Route>,
    named: Named,
    stored: (section: StoredSection<Route>) => void,
  ) => void
}

/**
 * The save of one section, kept apart from every other part's: its own
 * request, aborted when the part goes, and its own lines.
 *
 * Invariant: what the part shows after "Saved" is what the database holds
 * for its section, and at most one of its saves is in flight. So the part
 * is held while a save is out: nothing can change what the answer will
 * replace, and Save cannot send a second body.
 */
export function useProfilePart<Route extends SectionRoute>(
  route: Route,
  initial: StoredSection<Route> | null,
  notSaved: string,
): ProfilePart<Route> {
  const { getToken } = useAuth()
  const [answered, setAnswered] = useState(initial !== null)
  const [notice, setNotice] = useState('')
  const [save, setSave] = useState<SaveShown>({ kind: 'idle' })
  const controller = useRef<AbortController | null>(null)
  const held = save.kind === 'saving'

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
    setNotice('')
    setSave({ kind: 'idle' })
  }

  function send(
    body: SectionBody<Route>,
    named: Named,
    stored: (section: StoredSection<Route>) => void,
  ): void {
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
        stored(saved.section)
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
