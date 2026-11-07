import { useAuth } from '@clerk/react'
import { useEffect, useState } from 'react'
import { fetchMe, type MeAnswer, type MeCheck } from '../api/me.ts'

type Shown = MeAnswer | 'checking'

const MESSAGES: Record<Shown, string> = {
  checking: 'Confirming your sign-in with the service…',
  recognised: 'Signed in',
  refused: 'The service did not accept your sign-in',
  unavailable: 'Could not confirm your sign-in with the service',
}

type GetToken = ReturnType<typeof useAuth>['getToken']

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

async function confirmSignIn(
  getToken: GetToken,
  signal: AbortSignal,
): Promise<MeCheck> {
  let token: string | null
  try {
    token = await getToken()
  } catch {
    return signal.aborted ? 'aborted' : 'unavailable'
  }
  if (signal.aborted) {
    return 'aborted'
  }
  // Clerk has no session token to give, so there is nothing to recognise.
  if (token === null) {
    return 'refused'
  }
  return fetchMe(token, signal)
}
