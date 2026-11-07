import { useEffect, useState } from 'react'
import { fetchHealth, type ServiceHealth } from '../api/health.ts'

type Shown = ServiceHealth | 'checking'

const MESSAGES: Record<Shown, string> = {
  checking: 'Checking the service…',
  ok: 'Service is up',
  unavailable: 'Service is unavailable',
}

/**
 * Asks the backend on mount, and again each time the page comes back into
 * view, and says whether it answered. Only the newest check is ever shown.
 */
export function ServiceStatus() {
  const [shown, setShown] = useState<Shown>('checking')

  useEffect(() => {
    let controller = new AbortController()

    function check() {
      controller.abort()
      controller = new AbortController()
      void fetchHealth(controller.signal).then((health) => {
        // An aborted check has been replaced by a newer one, or belongs to an
        // effect that has been cleaned up. Strict mode's rehearsal unmount and
        // remount keeps this component and its state, so showing that answer
        // would replace the live check's.
        if (health !== 'aborted') {
          setShown(health)
        }
      })
    }

    // A page left open in a background tab would otherwise go on saying the
    // service is up long after it stopped.
    function checkWhenVisible() {
      if (document.visibilityState === 'visible') {
        setShown('checking')
        check()
      }
    }

    check()
    document.addEventListener('visibilitychange', checkWhenVisible)
    return () => {
      document.removeEventListener('visibilitychange', checkWhenVisible)
      controller.abort()
    }
  }, [])

  return <p role="status">{MESSAGES[shown]}</p>
}
