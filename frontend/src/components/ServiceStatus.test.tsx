import { act, render, screen } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HealthBody } from '../api/health.ts'
import { ServiceStatus } from './ServiceStatus.tsx'

const OK = { status: 'ok', database: 'ok' } satisfies HealthBody
const UNAVAILABLE = {
  status: 'unavailable',
  database: 'unreachable',
} satisfies HealthBody

// Typed against the generated contract, so the bodies change with the backend's.
function answer(status: number, body: HealthBody): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// A reply the test sends when it chooses, after reading the page meanwhile.
function laterAnswer(): {
  reply: Promise<Response>
  send: (response: Response) => void
} {
  let send: (response: Response) => void = () => {}
  const reply = new Promise<Response>((resolve) => {
    send = resolve
  })
  return { reply, send }
}

function showPage(state: DocumentVisibilityState): void {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue(state)
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

// Lets settled requests reach the component before the page is read.
async function settle(): Promise<void> {
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)))
}

describe('ServiceStatus', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
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
      vi.fn(async () => answer(200, OK)),
    )

    render(<ServiceStatus />)

    expect(await screen.findByText('Service is up')).toBe(
      screen.getByRole('status'),
    )
  })

  it('says the service is unavailable when it does not answer ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => answer(503, UNAVAILABLE)),
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

  it('checks again when the page comes back into view', async () => {
    const second = laterAnswer()
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(answer(200, OK))
        .mockReturnValueOnce(second.reply),
    )
    render(<ServiceStatus />)
    expect(await screen.findByText('Service is up')).toBe(
      screen.getByRole('status'),
    )

    showPage('hidden')
    showPage('visible')

    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking the service…',
    )
    second.send(answer(503, UNAVAILABLE))
    expect(await screen.findByText('Service is unavailable')).toBe(
      screen.getByRole('status'),
    )
  })

  it('starts no check when the page is hidden', async () => {
    const fetchMock = vi.fn(async () => answer(200, OK))
    vi.stubGlobal('fetch', fetchMock)
    render(<ServiceStatus />)
    await screen.findByText('Service is up')

    showPage('hidden')
    await settle()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status')).toHaveTextContent('Service is up')
  })

  it('aborts a check in flight when the page comes back and never shows its answer', async () => {
    const first = laterAnswer()
    const second = laterAnswer()
    const signals: (AbortSignal | undefined)[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        signals.push(init?.signal ?? undefined)
        return signals.length === 1 ? first.reply : second.reply
      }),
    )
    render(<ServiceStatus />)

    showPage('visible')
    expect(signals).toHaveLength(2)
    expect(signals[0]?.aborted).toBe(true)

    // The first request ignores its abort and answers late.
    first.send(answer(200, OK))
    await settle()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking the service…',
    )

    second.send(answer(503, UNAVAILABLE))
    expect(await screen.findByText('Service is unavailable')).toBe(
      screen.getByRole('status'),
    )
  })

  it('starts no check when the page comes back after it unmounts', async () => {
    const fetchMock = vi.fn(async () => answer(200, OK))
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = render(<ServiceStatus />)
    await screen.findByText('Service is up')

    unmount()
    showPage('hidden')
    showPage('visible')
    await settle()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
