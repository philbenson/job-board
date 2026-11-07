import { useAuth } from '@clerk/react'
import { useEffect, useId, useRef, useState } from 'react'
import {
  fetchLeads,
  type Lead,
  type LeadsRead,
  type Loaded,
} from '../api/leads.ts'
import { withToken } from '../api/withToken.ts'

// One limit for each exchange, Clerk's session token included, so a token
// that never comes is no reply too. The request's own limit is as long and
// starts later, so this one is always the one that gives up.
const EXCHANGE_TIMEOUT_MS = 5_000

// The top of the backend's scale, said with every score.
const HIGHEST_SCORE = 5

// The person's own locale, from the browser.
const DATE = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

const LOADING = 'Loading your leads…'
const NOT_LOADED = 'Could not load your leads.'
const NOT_REFRESHED = 'Could not refresh your leads.'

// What the person is waiting on: the first load, or a read they asked for
// with Retry. A refresh as the page comes back into view keeps quiet.
type Reading = 'first' | 'retry' | null

/**
 * The signed-in person's leads, best first, as the backend ordered them.
 * Asks on mount, and again each time the page comes back into view, so a tab
 * left open picks up the postings scored meanwhile. Only the newest answer is
 * ever shown, and a list already shown stays until a new list replaces it: a
 * refresh that fails keeps it, says so, and offers Retry.
 * Everything from a posting is shown as text.
 *
 * The status and alert lines stay on the page, empty when there is nothing to
 * say, so a screen reader hears each change of their words. Retry stays on
 * the page while the read it asked for runs, held with aria-disabled rather
 * than disabled, which would drop keyboard focus to the page, and its handler
 * does nothing meanwhile. When a list loads, Retry leaves the page: if it
 * held focus, focus goes to the heading rather than to the page; otherwise
 * focus stays where it is.
 */
export function LeadsPanel() {
  const { getToken } = useAuth()
  // The newest list the service gave, kept through any failure since.
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  // Whether the newest answer was a failure.
  const [failed, setFailed] = useState(false)
  const [reading, setReading] = useState<Reading>('first')
  // Bumped by Retry, to run the loading effect again.
  const [attempt, setAttempt] = useState(0)
  const headingId = useId()
  const heading = useRef<HTMLHeadingElement>(null)
  const retryButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let controller: AbortController | undefined

    function load() {
      controller?.abort()
      controller = new AbortController()
      // No token to give is no answer either.
      void withToken(
        getToken,
        EXCHANGE_TIMEOUT_MS,
        controller.signal,
        fetchLeads,
        'unavailable',
      ).then((read: LeadsRead) => {
        // An aborted load has been replaced by a newer one, or belongs to an
        // effect that has been cleaned up; see ServiceStatus for why its
        // answer must not be shown.
        if (read === 'aborted') {
          return
        }
        setReading(null)
        if (read === 'unavailable') {
          setFailed(true)
        } else {
          setFailed(false)
          setLoaded(read)
          // Retry leaves the page with this answer. The heading stays, so it
          // can take focus now, before Retry goes.
          const retryFocused =
            retryButton.current !== null &&
            document.activeElement === retryButton.current
          if (retryFocused) {
            heading.current?.focus()
          }
        }
      })
    }

    function loadWhenVisible() {
      if (document.visibilityState === 'visible') {
        load()
      }
    }

    load()
    document.addEventListener('visibilitychange', loadWhenVisible)
    return () => {
      document.removeEventListener('visibilitychange', loadWhenVisible)
      controller?.abort()
    }
  }, [getToken, attempt])

  function retry(): void {
    if (reading !== null) {
      return
    }
    setReading('retry')
    setFailed(false)
    setAttempt((count) => count + 1)
  }

  let problem = ''
  if (failed) {
    problem = loaded === null ? NOT_LOADED : NOT_REFRESHED
  }

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} ref={heading} tabIndex={-1}>
        Your leads
      </h2>
      <p role="status">{reading === null ? '' : LOADING}</p>
      <p role="alert">{problem}</p>
      {(failed || reading === 'retry') && (
        <button
          ref={retryButton}
          type="button"
          aria-disabled={reading !== null}
          onClick={retry}
        >
          Retry
        </button>
      )}
      {loaded !== null &&
        (loaded.leads.length === 0 ? (
          <p>
            No leads yet. Leads appear once your model key and at least one
            target title are saved and scoring next runs.
          </p>
        ) : (
          <LeadList leads={loaded.leads} total={loaded.total} />
        ))}
    </section>
  )
}

function LeadList({ leads, total }: { leads: Lead[]; total: number }) {
  return (
    <>
      {/* Scoring rates each posting once per person, so a change of profile
          re-scores nothing already rated. */}
      <p>
        Each lead was rated against your profile as it was when the lead was
        scored. A change to your profile applies to postings rated after it.
      </p>
      {/* Scoring takes the newest unrated postings first, a capped number
          each run; the cap is left out so it can change without the page. */}
      <p>
        Newer postings are rated first; older ones follow on later runs while
        there is room.
      </p>
      <ol aria-label="Your leads, best first">
        {leads.map((lead) => (
          <LeadItem key={lead.posting_id} lead={lead} />
        ))}
      </ol>
      {total > leads.length && (
        <p>
          Showing the best {leads.length} of {total}.
        </p>
      )}
    </>
  )
}

function LeadItem({ lead }: { lead: Lead }) {
  return (
    <li>
      <h3>
        {isWebAddress(lead.url) ? (
          <a href={lead.url} target="_blank" rel="noopener noreferrer">
            {lead.title}
          </a>
        ) : (
          lead.title
        )}
      </h3>
      <p>
        {lead.location === null
          ? lead.company
          : `${lead.company} · ${lead.location}`}
      </p>
      <p>
        {lead.score} out of {HIGHEST_SCORE}
      </p>
      <p>{lead.reason}</p>
      <p>
        {lead.published_at !== null && (
          <>
            <span>Published {formatDate(lead.published_at)}</span>
            {' · '}
          </>
        )}
        <span>Rated {formatDate(lead.scored_at)}</span>
      </p>
    </li>
  )
}

// The fetcher stores only absolute http and https addresses, but the page
// does not rely on it: any other scheme, such as javascript:, would run or
// show something other than the posting.
function isWebAddress(url: string): boolean {
  try {
    const { protocol } = new URL(url)
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}

function formatDate(iso: string): string {
  return DATE.format(new Date(iso))
}
