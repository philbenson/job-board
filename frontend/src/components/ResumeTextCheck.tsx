import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState } from 'react'
import {
  fetchResumeText,
  RESUME_TEXT_TIMEOUT_MS,
  saveResumeText,
  type ReadState,
  type ResumeText,
  type TextRead,
  type TextSave,
} from '../api/resumeText.ts'
import { withToken } from '../api/withToken.ts'
import { timeOf } from './timeOf.ts'

// The backend holds the same cap and refuses past it.
const MAX_RESUME_TEXT_LENGTH = 15_000

const NOT_SET_UP = 'Resume storage is not set up on this service yet'
const STORAGE_DOWN = 'Could not reach resume storage; try again later'
const SAVING = "Saving your resume's text…"
const SAVED = 'Saved.'
const REPLACED =
  'Your resume was replaced since this text was read. Reload the page to check the new text.'

/** What the status line says once the text is read, by how reading the file went. */
const READ_LINES: Record<NonNullable<ReadState> | 'none', string> = {
  found:
    'Here is the text read from your resume. Check it, put anything out of order back in order, and save it.',
  cut: "Your resume's text is longer than 15,000 characters, so only the first 15,000 are here. Check them and save.",
  none_found:
    'No text could be read from your resume; it may be a scanned image. Type or paste its text here and save it.',
  failed: "Your resume's text could not be read. Type or paste its text here and save it.",
  none: 'This resume was uploaded before its text was read. Upload it again to read its text.',
}

/**
 * The text read from the signed-in person's resume, for them to check,
 * correct or type in, and save. Reads it once on mount; the resume panel
 * keys it on the upload time, so a new file mounts a new one.
 *
 * Invariant: the save names the upload by the exact time string the read
 * gave, so a check is never kept for a file it was not read from. One
 * `role="status"` line and one `role="alert"` line stay mounted from the
 * first render, empty, and only their words change, which is what a screen
 * reader announces. Save is held with aria-disabled and a guarded handler, as
 * the resume panel's buttons are, so focus stays on it; while a save is out
 * the box is held too, so what it shows after the answer is what was saved.
 */
export function ResumeTextCheck() {
  const { getToken } = useAuth()
  const [held, setHeld] = useState<ResumeText | null>(null)
  const [text, setText] = useState('')
  const [said, setSaid] = useState('')
  const [alerted, setAlerted] = useState('')
  const [saving, setSaving] = useState(false)
  const saveController = useRef<AbortController | null>(null)
  const headingId = useId()
  const boxId = useId()
  const countId = useId()
  const length = [...text].length
  const overCap = length > MAX_RESUME_TEXT_LENGTH

  useEffect(() => {
    const controller = new AbortController()
    void withToken(
      getToken,
      RESUME_TEXT_TIMEOUT_MS,
      controller.signal,
      fetchResumeText,
      'unavailable',
    ).then((read: TextRead) => {
      // An aborted read belongs to an effect that has been cleaned up; see
      // ServiceStatus for why its answer must not be shown.
      if (read === 'aborted') {
        return
      }
      if (typeof read === 'string') {
        setAlerted(failure(read, "Could not load your resume's text"))
        return
      }
      setHeld(read.resumeText)
      setText(read.resumeText.text ?? '')
      setSaid(READ_LINES[read.resumeText.state ?? 'none'])
    })
    return () => {
      controller.abort()
    }
  }, [getToken])

  // A save still out when the check goes has nobody to tell.
  useEffect(
    () => () => {
      saveController.current?.abort()
    },
    [],
  )

  async function save(): Promise<void> {
    if (held === null || saving || overCap) {
      return
    }
    const controller = new AbortController()
    saveController.current = controller
    setSaving(true)
    setSaid(SAVING)
    setAlerted('')
    const uploadedAt = held.uploadedAt
    const saved: TextSave = await withToken(
      getToken,
      RESUME_TEXT_TIMEOUT_MS,
      controller.signal,
      (token, signal) => saveResumeText(token, text, uploadedAt, signal),
      'unavailable',
    )
    if (saved === 'aborted') {
      return
    }
    setSaving(false)
    if (typeof saved === 'string' || saved.kind === 'refused') {
      setSaid('')
      setAlerted(
        saved === 'replaced'
          ? REPLACED
          : typeof saved === 'string'
            ? failure(saved, "Could not save your resume's text")
            : saved.message,
      )
      return
    }
    // What the backend kept, which it cleaned.
    setHeld(saved.resumeText)
    setText(saved.resumeText.text ?? '')
    setSaid(SAVED)
  }

  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId}>Resume text</h3>
      <p role="status">{said}</p>
      {held?.checkedAt != null && <p>{`You checked this text on ${timeOf(held.checkedAt)}.`}</p>}
      {held !== null && (
        <>
          <label htmlFor={boxId}>Your resume's text</label>
          <textarea
            id={boxId}
            value={text}
            rows={20}
            aria-describedby={countId}
            // Held while a save is out, as ProfilePanel holds its inputs, so
            // the saved text the answer brings never overwrites words typed
            // since; readOnly keeps focus where it is.
            readOnly={saving}
            aria-disabled={saving}
            onChange={(event) => {
              if (saving) {
                return
              }
              setText(event.target.value)
              // Saved no longer holds once the text differs from what was.
              if (said === SAVED) {
                setSaid('')
              }
            }}
          />
          <p id={countId}>
            {length.toLocaleString('en-US')} of {MAX_RESUME_TEXT_LENGTH.toLocaleString('en-US')}{' '}
            characters
          </p>
          <button
            type="button"
            aria-disabled={saving || overCap}
            onClick={() => {
              void save()
            }}
          >
            Save
          </button>
        </>
      )}
      <p role="alert">{alerted}</p>
    </section>
  )
}

function failure(
  outcome: 'no resume' | 'not set up' | 'storage down' | 'unavailable',
  otherwise: string,
): string {
  if (outcome === 'not set up') {
    return NOT_SET_UP
  }
  return outcome === 'storage down' ? STORAGE_DOWN : otherwise
}
