import { askWithin } from './askWithin.ts'

/**
 * Asks with Clerk's session token, under one time limit for the token and the
 * request together, so a token that never comes is no answer too. Without a
 * token there is nobody to ask for: that resolves to `noToken`, which each
 * caller names, and nothing is sent.
 */
export function withToken<T, NoToken extends string>(
  getToken: () => Promise<string | null>,
  limitMs: number,
  signal: AbortSignal,
  ask: (token: string, signal: AbortSignal) => Promise<T>,
  noToken: NoToken,
): Promise<T | NoToken | 'unavailable' | 'aborted'> {
  return askWithin(limitMs, signal, async (askSignal): Promise<T | NoToken> => {
    const token = await getToken()
    if (token === null || askSignal.aborted) {
      return noToken
    }
    return ask(token, askSignal)
  })
}
