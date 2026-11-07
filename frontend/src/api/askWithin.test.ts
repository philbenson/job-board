import { afterEach, describe, expect, it, vi } from 'vitest'
import { askWithin } from './askWithin.ts'

// An ask that never settles, whatever happens to its signal.
function never(): Promise<string> {
  return new Promise(() => {})
}

describe('askWithin', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns the answer', async () => {
    await expect(askWithin(5_000, undefined, async () => 'yes')).resolves.toBe(
      'yes',
    )
  })

  it('reports unavailable when the ask fails', async () => {
    const fails = async (): Promise<string> => {
      throw new TypeError('Failed to fetch')
    }

    await expect(askWithin(5_000, undefined, fails)).resolves.toBe(
      'unavailable',
    )
  })

  it('reports unavailable when the ask throws before it returns a promise', async () => {
    vi.useFakeTimers()
    const throws = (): Promise<string> => {
      throw new TypeError('not a function')
    }

    await expect(askWithin(5_000, undefined, throws)).resolves.toBe(
      'unavailable',
    )
    // Its time limit went with it.
    expect(vi.getTimerCount()).toBe(0)
  })

  it('gives up at the time limit even when the ask never settles', async () => {
    vi.useFakeTimers()
    let result: string | undefined
    void askWithin(5_000, new AbortController().signal, never).then(
      (outcome) => {
        result = outcome
      },
    )

    await vi.advanceTimersByTimeAsync(4_999)
    expect(result).toBeUndefined()
    await vi.advanceTimersByTimeAsync(1)
    expect(result).toBe('unavailable')
  })

  it("aborts the ask's signal at the time limit, without aborting the caller's", async () => {
    vi.useFakeTimers()
    let askSignal: AbortSignal | undefined
    const caller = new AbortController()
    void askWithin(5_000, caller.signal, (signal) => {
      askSignal = signal
      return never()
    })

    await vi.advanceTimersByTimeAsync(5_000)

    expect(askSignal?.aborted).toBe(true)
    expect(caller.signal.aborted).toBe(false)
  })

  it('reports aborted as soon as the caller aborts, even when the ask never settles', async () => {
    let askSignal: AbortSignal | undefined
    const caller = new AbortController()
    const result = askWithin(5_000, caller.signal, (signal) => {
      askSignal = signal
      return never()
    })

    caller.abort()

    await expect(result).resolves.toBe('aborted')
    expect(askSignal?.aborted).toBe(true)
  })

  it('reports aborted, not the answer, when the caller aborted before it came', async () => {
    const caller = new AbortController()
    const result = askWithin(5_000, caller.signal, async () => {
      caller.abort()
      return 'yes'
    })

    await expect(result).resolves.toBe('aborted')
  })

  it('reports aborted without asking when the caller has already aborted', async () => {
    const caller = new AbortController()
    caller.abort()
    const ask = vi.fn(async () => 'yes')

    await expect(askWithin(5_000, caller.signal, ask)).resolves.toBe('aborted')
    expect(ask).not.toHaveBeenCalled()
  })
})
