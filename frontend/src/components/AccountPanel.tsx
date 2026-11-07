import { useAuth } from '@clerk/react'
import { useEffect, useState } from 'react'
import { fetchMe, type MeAnswer, type MeCheck } from '../api/me.ts'
import { withToken } from '../api/withToken.ts'

type Shown = MeAnswer | 'checking'

const MESSAGES: Record<Shown, string> = {
  checking: 'Confirming your sign-in with the service…',
  recognised: 'Signed in',
  refused: 'The service did not accept your sign-in',
  unavailable: 'Could not confirm your sign-in with the service',
}

type GetToken = ReturnType<typeof useAuth>['getToken']

// One limit for the whole confirmation, Clerk's session token included, so a
// token that never comes is no reply too. The me request's own limit is as
// long and starts later, so this one is always the one that gives up.
const CONFIRM_TIMEOUT_MS = 5_000

/**
 * Sends the signed-in person's session token to the backend once on mount and
 * says what the backend made of it. It says "Signed in" only when the backend
 * recognised the person: Clerk's own word is not enough.
 */
export function AccountPanel() {
  const { getToken } = useAuth()
  const [shown, setShown] = useState<Shown>('checking')

  useEffect(() => {
    const controller = new AbortController()
    void confirmSignIn(getToken, controller.signal).then((me) => {
      // An aborted check belongs to an effect that has been cleaned up; see
      // ServiceStatus for why its answer must not be shown.
      if (me !== 'aborted') {
        setShown(me)
      }
    })
    return () => {
      controller.abort()
    }
  }, [getToken])

  return <p role="status">{MESSAGES[shown]}</p>
}

function confirmSignIn(
  getToken: GetToken,
  signal: AbortSignal,
): Promise<MeCheck> {
  // Clerk having no session token to give leaves nothing to recognise.
  return withToken(getToken, CONFIRM_TIMEOUT_MS, signal, fetchMe, 'refused')
}
