/** No usable answer in time, or the ask failed. */
export type Unavailable = 'unavailable'

/** The caller aborted, so nobody wants the answer. */
export type Aborted = 'aborted'

/**
 * Runs `ask` under a time limit and the caller's signal. Resolves to its
 * answer; to "unavailable" when it fails or has not answered within
 * `limitMs`; or to "aborted" once the caller's signal has aborted, and never
 * otherwise. It resolves at the limit or the abort even when `ask` never
 * settles, and aborts the signal it hands `ask` at either, so a request the
 * ask made is cancelled. Never rejects.
 */
export function askWithin<T>(
  limitMs: number,
  signal: AbortSignal | undefined,
  ask: (signal: AbortSignal) => Promise<T>,
): Promise<T | Unavailable | Aborted> {
  if (signal?.aborted) {
    return Promise.resolve('aborted')
  }
  // Its own controller, so the time limit cancels the ask without making the
  // caller's signal read as aborted.
  const timeout = new AbortController()
  const askSignal =
    signal === undefined
      ? timeout.signal
      : AbortSignal.any([signal, timeout.signal])

  return new Promise((resolve) => {
    // The first outcome wins; a later one finds the promise settled.
    const finish = (outcome: T | Unavailable): void => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      resolve(signal?.aborted ? 'aborted' : outcome)
    }
    const onAbort = (): void => {
      finish('unavailable')
    }
    const timer = setTimeout(() => {
      timeout.abort()
      finish('unavailable')
    }, limitMs)
    signal?.addEventListener('abort', onAbort)

    ask(askSignal).then(finish, () => {
      finish('unavailable')
    })
  })
}
