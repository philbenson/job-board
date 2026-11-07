import { afterEach, describe, expect, it, vi } from 'vitest'
import { withToken } from './withToken.ts'

const TOKEN = 'header.payload.signature'

function asker() {
  return vi.fn((token: string, _signal: AbortSignal) =>
    Promise.resolve(`asked with ${token}`),
  )
}

describe('withToken', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('asks with the session token and resolves to the answer', async () => {
    const ask = asker()

    const answer = await withToken(
      () => Promise.resolve(TOKEN),
      5_000,
      new AbortController().signal,
      ask,
      'refused',
    )

    expect(answer).toBe(`asked with ${TOKEN}`)
    expect(ask).toHaveBeenCalledTimes(1)
  })

  it.each(['refused', 'unavailable'] as const)(
    'resolves to %s when Clerk has no token, and asks nothing',
    async (noToken) => {
      const ask = asker()

      const answer = await withToken(
        () => Promise.resolve(null),
        5_000,
        new AbortController().signal,
        ask,
        noToken,
      )

      expect(answer).toBe(noToken)
      expect(ask).not.toHaveBeenCalled()
    },
  )

  it('asks nothing with a token that comes after the limit', async () => {
    vi.useFakeTimers()
    const ask = asker()
    const lateToken = () =>
      new Promise<string>((resolve) => {
        setTimeout(() => {
          resolve(TOKEN)
        }, 6_000)
      })

    const answer = withToken(
      lateToken,
      5_000,
      new AbortController().signal,
      ask,
      'unavailable',
    )
    await vi.advanceTimersByTimeAsync(6_000)

    await expect(answer).resolves.toBe('unavailable')
    expect(ask).not.toHaveBeenCalled()
  })

  it('resolves to aborted when the caller aborts', async () => {
    const controller = new AbortController()
    const ask = vi.fn(
      (_token: string, _signal: AbortSignal) => new Promise<string>(() => {}),
    )

    const answer = withToken(
      () => Promise.resolve(TOKEN),
      5_000,
      controller.signal,
      ask,
      'refused',
    )
    controller.abort()

    await expect(answer).resolves.toBe('aborted')
  })
})
