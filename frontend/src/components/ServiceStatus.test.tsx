import { act, render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ServiceStatus } from './ServiceStatus.tsx'

function answer(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ServiceStatus', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('says it is checking while the service has not answered', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    )

    render(<ServiceStatus />)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking the service…',
    )
  })

  it('says the service is up once it answers ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(200, '{"status": "ok", "database": "ok"}')),
    )

    render(<ServiceStatus />)

    expect(await screen.findByText('Service is up')).toBe(
      screen.getByRole('status'),
    )
  })

  it('says the service is unavailable when it does not answer ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        answer(503, '{"status": "unavailable", "database": "unreachable"}'),
      ),
    )

    render(<ServiceStatus />)

    expect(await screen.findByText('Service is unavailable')).toBe(
      screen.getByRole('status'),
    )
  })

  it('aborts its request when it unmounts', () => {
    let signal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        signal = init?.signal ?? undefined
        return new Promise<Response>(() => {})
      }),
    )

    const { unmount } = render(<ServiceStatus />)
    expect(signal?.aborted).toBe(false)

    unmount()

    expect(signal?.aborted).toBe(true)
  })

  it('ignores the answer to a request it aborted', async () => {
    // Strict mode mounts twice, aborting the first request; a fetch that
    // rejects on abort makes that request resolve as unavailable.
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('The request was aborted', 'AbortError'))
          })
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    render(
      <StrictMode>
        <ServiceStatus />
      </StrictMode>,
    )
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)))

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking the service…',
    )
  })
})
