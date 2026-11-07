import { render, screen } from '@testing-library/react'
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

function serviceNeverAnswers() {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>(() => {})),
  )
}

describe('App', () => {
  beforeEach(() => {
    clerk.signedIn = false
    clerk.providerKeys = []
    clerk.getToken.mockReset()
  })

  afterEach(() => {
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
})
