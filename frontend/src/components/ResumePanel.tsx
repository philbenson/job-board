import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState } from 'react'
import {
  fetchResume,
  removeResume,
  RESUME_READ_TIMEOUT_MS,
  RESUME_REMOVE_TIMEOUT_MS,
  RESUME_UPLOAD_TIMEOUT_MS,
  uploadResume,
  type Resume,
  type ResumeRead,
  type ResumeRemoval,
  type ResumeUpload,
} from '../api/resume.ts'
import { withToken } from '../api/withToken.ts'

// The backend holds the same cap and refuses past it; checking here first lets
// the person hear it at once, before 5 MB goes up a slow line for nothing.
const MAX_RESUME_BYTES = 5 * 1024 * 1024
// How every PDF file starts, which the backend checks too.
const PDF_SIGNATURE = '%PDF-'

const KILOBYTE = 1024
const MEGABYTE = 1024 * 1024

const NOT_SET_UP = 'Resume storage is not set up on this service yet'
const STORAGE_DOWN = 'Could not reach resume storage; try again later'

type Loading =
  | { kind: 'loading' }
  | { kind: 'loaded'; resume: Resume | null }
  | { kind: 'not set up' }
  | { kind: 'unavailable' }

/** What the status line says, and whether a request is out. */
type Shown =
  | { kind: 'idle' }
  | { kind: 'uploading' }
  | { kind: 'removing' }
  | { kind: 'said'; message: string }

/**
 * The signed-in person's resume: loads it once on mount, shows its size and
 * when it was uploaded, and uploads a chosen PDF or removes the one held.
 *
 * Invariant: at most one request is out at a time, and what is shown after
 * one answers is what the backend recorded. While one is out the buttons are
 * held with aria-disabled and guarded handlers rather than disabled, which
 * would drop keyboard focus to the page, as ProfilePanel does.
 */
export function ResumePanel() {
  const { getToken } = useAuth()
  const [loading, setLoading] = useState<Loading>({ kind: 'loading' })
  const [chosen, setChosen] = useState<File | null>(null)
  const [shown, setShown] = useState<Shown>({ kind: 'idle' })
  const requestController = useRef<AbortController | null>(null)
  const chooser = useRef<HTMLInputElement>(null)
  const held = shown.kind === 'uploading' || shown.kind === 'removing'
  const headingId = useId()
  const chooserId = useId()

  useEffect(() => {
    const controller = new AbortController()
    // No token to give is no answer either.
    void withToken(
      getToken,
      RESUME_READ_TIMEOUT_MS,
      controller.signal,
      fetchResume,
      'unavailable',
    ).then((read: ResumeRead) => {
      // An aborted load belongs to an effect that has been cleaned up; see
      // ServiceStatus for why its answer must not be shown.
      if (read === 'aborted') {
        return
      }
      if (read === 'not set up') {
        setLoading({ kind: 'not set up' })
      } else if (read === 'unavailable' || read === 'storage down') {
        setLoading({ kind: 'unavailable' })
      } else {
        setLoading({ kind: 'loaded', resume: read.resume })
      }
    })
    return () => {
      controller.abort()
    }
  }, [getToken])

  // A request still out when the panel goes has nobody to tell.
  useEffect(
    () => () => {
      requestController.current?.abort()
    },
    [],
  )

  function begin(kind: 'uploading' | 'removing'): AbortSignal {
    const controller = new AbortController()
    requestController.current = controller
    setShown({ kind })
    return controller.signal
  }

  function say(message: string): void {
    setShown({ kind: 'said', message })
  }

  async function upload(): Promise<void> {
    if (held) {
      return
    }
    if (chosen === null) {
      say('Choose a PDF first')
      return
    }
    // Read from the file itself, not its name or the type the browser guessed.
    if (chosen.size > MAX_RESUME_BYTES) {
      say('A resume can be at most 5 MB')
      return
    }
    const file = chosen
    const signal = begin('uploading')
    let startsRight: boolean
    try {
      startsRight = await startsAsAPdf(file)
    } catch {
      // The browser cannot read a file that changed or went on disk after it
      // was chosen, until it is chosen again.
      say('Could not read that file; choose it again')
      return
    }
    if (!startsRight) {
      say('That file is not a PDF')
      return
    }
    const uploaded: ResumeUpload = await withToken(
      getToken,
      RESUME_UPLOAD_TIMEOUT_MS,
      signal,
      (token, tokenSignal) => uploadResume(token, file, tokenSignal),
      'unavailable',
    )
    if (uploaded === 'aborted') {
      return
    }
    if (typeof uploaded === 'string') {
      say(failure(uploaded, 'Could not upload your resume'))
      return
    }
    setLoading({ kind: 'loaded', resume: uploaded.resume })
    // A file chosen while this one went up is kept, to be sent next.
    setChosen((current) => (current === file ? null : current))
    if (chooser.current?.files?.[0] === file) {
      chooser.current.value = ''
    }
    say('Resume uploaded')
  }

  async function remove(): Promise<void> {
    if (held) {
      return
    }
    const signal = begin('removing')
    const removal: ResumeRemoval = await withToken(
      getToken,
      RESUME_REMOVE_TIMEOUT_MS,
      signal,
      removeResume,
      'unavailable',
    )
    if (removal === 'aborted') {
      return
    }
    if (removal !== 'removed') {
      say(failure(removal, 'Could not remove your resume'))
      return
    }
    setLoading({ kind: 'loaded', resume: null })
    say('Resume removed')
    // The Remove button goes with the resume, and would take focus with it.
    chooser.current?.focus()
  }

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>Resume</h2>
      {loading.kind === 'loading' && <p role="status">Loading your resume…</p>}
      {loading.kind === 'unavailable' && <p role="alert">Could not load your resume</p>}
      {loading.kind === 'not set up' && <p>{NOT_SET_UP}</p>}
      {loading.kind === 'loaded' && (
        <>
          <p>
            {loading.resume === null
              ? 'No resume yet'
              : `${sizeOf(loading.resume.sizeBytes)}, uploaded ${timeOf(loading.resume.uploadedAt)}`}
          </p>
          <label htmlFor={chooserId}>Choose a PDF</label>{' '}
          <input
            id={chooserId}
            ref={chooser}
            type="file"
            accept="application/pdf,.pdf"
            aria-disabled={held}
            onChange={(event) => {
              // aria-disabled does not stop a file input opening, so a choice
              // made while a request is out is taken too: what the input
              // shows is what is sent next.
              setChosen(event.target.files?.[0] ?? null)
              if (!held) {
                setShown({ kind: 'idle' })
              }
            }}
          />{' '}
          <button
            type="button"
            aria-disabled={held}
            onClick={() => {
              void upload()
            }}
          >
            {loading.resume === null ? 'Upload' : 'Replace'}
          </button>
          {loading.resume !== null && (
            <>
              {' '}
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
          {/* The status line stays on the page while the panel shows, and
              changes its words, which is what a screen reader announces. */}
          <p role="status">{statusLine(shown)}</p>
        </>
      )}
    </section>
  )
}

function statusLine(shown: Shown): string {
  switch (shown.kind) {
    case 'idle':
      return ''
    case 'uploading':
      return 'Uploading your resume…'
    case 'removing':
      return 'Removing your resume…'
    case 'said':
      return shown.message
  }
}

function failure(outcome: 'not set up' | 'storage down' | 'unavailable', otherwise: string): string {
  if (outcome === 'not set up') {
    return NOT_SET_UP
  }
  return outcome === 'storage down' ? STORAGE_DOWN : otherwise
}

async function startsAsAPdf(file: File): Promise<boolean> {
  const head = await file.slice(0, PDF_SIGNATURE.length).arrayBuffer()
  return new TextDecoder('latin1').decode(head) === PDF_SIGNATURE
}

// Kilobytes under a megabyte, as whole numbers and never 0; megabytes with
// one decimal from there. Binary units, as the 5 MB cap is.
function sizeOf(bytes: number): string {
  if (bytes < MEGABYTE) {
    return `${Math.max(1, Math.floor(bytes / KILOBYTE))} KB`
  }
  return `${(bytes / MEGABYTE).toFixed(1)} MB`
}

// In the browser's own locale and time zone.
function timeOf(uploadedAt: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(uploadedAt)
}
