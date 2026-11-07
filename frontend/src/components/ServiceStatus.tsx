import { useEffect, useState } from 'react'
import { fetchHealth, type ServiceHealth } from '../api/health.ts'

type Shown = ServiceHealth | 'checking'

const MESSAGES: Record<Shown, string> = {
  checking: 'Checking the service…',
  ok: 'Service is up',
  unavailable: 'Service is unavailable',
}

/** Asks the backend once on mount and says whether it answered. */
export function ServiceStatus() {
  const [shown, setShown] = useState<Shown>('checking')

  useEffect(() => {
    const controller = new AbortController()
    void fetchHealth(controller.signal).then((health) => {
      // An aborted request resolves as "unavailable"; it belongs to a
      // component that is gone, so its answer is dropped.
      if (!controller.signal.aborted) {
        setShown(health)
      }
    })
    return () => {
      controller.abort()
    }
  }, [])

  return <p role="status">{MESSAGES[shown]}</p>
}
