import { useAuth } from '@clerk/react'
import { useEffect, useId, useState } from 'react'
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

type Shown = 'loading' | 'unavailable' | Loaded

/**
 * The signed-in person's leads, best first, as the backend ordered them.
 * Asks on mount, and again each time the page comes back into view, so a tab
 * left open picks up the postings scored meanwhile. Only the newest answer is
 * ever shown, and a list already shown stays until that answer replaces it.
 * Everything from a posting is shown as text.
 */
export function LeadsPanel() {
  const { getToken } = useAuth()
  const [shown, setShown] = useState<Shown>('loading')
  // Bumped by Retry, to run the loading effect again.
  const [attempt, setAttempt] = useState(0)
  const headingId = useId()

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
        if (read !== 'aborted') {
          setShown(read)
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
    setShown('loading')
    setAttempt((count) => count + 1)
  }

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>Your leads</h2>
      {shown === 'loading' && <p role="status">Loading your leads…</p>}
      {shown === 'unavailable' && (
        <>
          <p role="alert">Could not load your leads.</p>
          <button type="button" onClick={retry}>
            Retry
          </button>
        </>
      )}
      {typeof shown === 'object' &&
        (shown.leads.length === 0 ? (
          <p>
            No leads yet. Postings are scored on a schedule once your model key
            and at least one target title are saved.
          </p>
        ) : (
          <LeadList leads={shown.leads} total={shown.total} />
        ))}
    </section>
  )
}

function LeadList({ leads, total }: { leads: Lead[]; total: number }) {
  return (
    <>
      {/* Scoring rates each posting once per person, so a change of titles
          re-scores nothing already rated. */}
      <p>
        Each lead was rated against your target titles as they were when it
        was scored. A change to your titles applies to postings rated after
        it.
      </p>
      {/* Scoring takes the newest unrated postings first, a capped number
          each run; the cap is left out so it can change without the page. */}
      <p>Newer postings are rated first; older ones follow on later runs.</p>
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
