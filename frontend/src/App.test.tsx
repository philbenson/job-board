import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'

// Clerk replaced by a stand-in whose sign-in state each test sets, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  signedIn: false,
  providerKeys: [] as (string | undefined)[],
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  ClerkProvider: (props: { publishableKey?: string; children: ReactNode }) => {
    clerk.providerKeys.push(props.publishableKey)
    return props.children
  },
  Show: (props: { when: string; children: ReactNode }) =>
    (props.when === 'signed-in') === clerk.signedIn ? props.children : null,
  SignInButton: (props: { children: ReactNode }) => props.children,
  UserButton: () => <button type="button" aria-label="Open user menu" />,
  useAuth: () => ({
    isLoaded: true,
    isSignedIn: clerk.signedIn,
    getToken: clerk.getToken,
  }),
}))

const PUBLISHABLE_KEY = 'pk_test_placeholder'

const SESSION_TOKEN = 'header.payload.signature'

const CHECKING = 'Confirming your sign-in with the service…'
const RECOGNISED = 'Signed in'
const REFUSED = 'The service did not accept your sign-in'
const UNAVAILABLE = 'Could not confirm your sign-in with the service'

function serviceNeverAnswers() {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>(() => {})),
  )
}

// The health check never answers; /api/me answers as the test says.
function serviceAnswersMe(
  me: (init?: RequestInit) => Promise<Response>,
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((url: string, init?: RequestInit) =>
    url === '/api/me' ? me(init) : new Promise<Response>(() => {}),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function answer(status: number, body: string): Promise<Response> {
  return Promise.resolve(
    new Response(body, {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

// A request that never answers, and fails the way fetch does when aborted.
function answerOnlyAbort(init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

describe('App', () => {
  beforeEach(() => {
    clerk.signedIn = false
    clerk.providerKeys = []
    clerk.getToken.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it.each([undefined, '', '   '])(
    'says sign-in is not configured, without mounting Clerk, for the key %j',
    (publishableKey) => {
      serviceNeverAnswers()

      render(<App publishableKey={publishableKey} />)

      expect(
        screen.getByRole('heading', { level: 1, name: 'Job board' }),
      ).toBeInTheDocument()
      expect(
        screen.getByText(/job postings scored against it, best first/),
      ).toBeInTheDocument()
      expect(screen.getByRole('status')).toHaveTextContent(
        'Checking the service…',
      )
      expect(screen.getByText(/Sign-in is not configured/)).toHaveTextContent(
        'VITE_CLERK_PUBLISHABLE_KEY',
      )
      expect(clerk.providerKeys).toEqual([])
      expect(screen.queryByRole('button')).not.toBeInTheDocument()
    },
  )

  it('offers Clerk sign-in, reachable by Tab, when signed out', async () => {
    serviceNeverAnswers()
    const user = userEvent.setup()

    render(<App publishableKey={PUBLISHABLE_KEY} />)
    await user.tab()

    expect(clerk.providerKeys[0]).toBe(PUBLISHABLE_KEY)
    expect(screen.getByRole('button', { name: 'Sign in' })).toHaveFocus()
    expect(screen.getByText('Checking the service…')).toBeInTheDocument()
    expect(screen.queryByText(/not configured/)).not.toBeInTheDocument()
  })

  it("shows Clerk's user button, reachable by Tab, when signed in", async () => {
    serviceNeverAnswers()
    clerk.signedIn = true
    clerk.getToken.mockReturnValue(new Promise(() => {}))
    const user = userEvent.setup()

    render(<App publishableKey={PUBLISHABLE_KEY} />)
    await user.tab()

    expect(screen.getByRole('button', { name: 'Open user menu' })).toHaveFocus()
    expect(
      screen.queryByRole('button', { name: 'Sign in' }),
    ).not.toBeInTheDocument()
  })

  describe('when signed in', () => {
    beforeEach(() => {
      clerk.signedIn = true
      clerk.getToken.mockResolvedValue(SESSION_TOKEN)
    })

    it('says signed in once the service recognises the session token', async () => {
      const fetchMock = serviceAnswersMe(() => answer(200, '{"id": 7}'))

      render(<App publishableKey={PUBLISHABLE_KEY} />)

      expect(screen.getByText(CHECKING)).toBeInTheDocument()
      expect(await screen.findByText(RECOGNISED)).toBeInTheDocument()
      const meCall = fetchMock.mock.calls.find(([url]) => url === '/api/me')
      const init = meCall?.[1] as RequestInit | undefined
      expect(new Headers(init?.headers).get('Authorization')).toBe(
        `Bearer ${SESSION_TOKEN}`,
      )
    })

    it.each([
      [
        'the service refuses the token',
        401,
        '{"detail": "sign-in required"}',
        REFUSED,
      ],
      [
        'the service answers without an id',
        200,
        '{"detail": "ok"}',
        UNAVAILABLE,
      ],
      ['the service fails', 503, '{"detail": "unavailable"}', UNAVAILABLE],
    ])(
      'never says signed in when %s',
      async (_case, status, body, message) => {
        serviceAnswersMe(() => answer(status, body))

        render(<App publishableKey={PUBLISHABLE_KEY} />)

        expect(await screen.findByText(message)).toBeInTheDocument()
        expect(screen.queryByText(RECOGNISED)).not.toBeInTheDocument()
      },
    )

    it('gives up after five seconds without an answer, never saying signed in', async () => {
      vi.useFakeTimers()
      serviceAnswersMe(answerOnlyAbort)

      render(<App publishableKey={PUBLISHABLE_KEY} />)
      await act(() => vi.advanceTimersByTimeAsync(4_999))
      expect(screen.getByText(CHECKING)).toBeInTheDocument()
      await act(() => vi.advanceTimersByTimeAsync(1))

      expect(screen.getByText(UNAVAILABLE)).toBeInTheDocument()
      expect(screen.queryByText(RECOGNISED)).not.toBeInTheDocument()
    })

    it('treats a missing session token as refused, without asking the service', async () => {
      clerk.getToken.mockResolvedValue(null)
      const fetchMock = serviceAnswersMe(() => answer(200, '{"id": 7}'))

      render(<App publishableKey={PUBLISHABLE_KEY} />)

      expect(await screen.findByText(REFUSED)).toBeInTheDocument()
      expect(fetchMock).not.toHaveBeenCalledWith('/api/me', expect.anything())
    })

    it('says it could not confirm the sign-in when the session token cannot be had', async () => {
      clerk.getToken.mockRejectedValue(new Error('network'))
      const fetchMock = serviceAnswersMe(() => answer(200, '{"id": 7}'))

      render(<App publishableKey={PUBLISHABLE_KEY} />)

      expect(await screen.findByText(UNAVAILABLE)).toBeInTheDocument()
      expect(fetchMock).not.toHaveBeenCalledWith('/api/me', expect.anything())
    })
  })
})
