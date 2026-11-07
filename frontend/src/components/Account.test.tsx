import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Account } from './Account.tsx'

// Clerk replaced by a stand-in whose sign-in state each test sets, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({ signedIn: false }))

vi.mock('@clerk/react', () => ({
  ClerkLoading: () => null,
  ClerkFailed: () => null,
  Show: (props: { when: string; children: ReactNode }) =>
    (props.when === 'signed-in') === clerk.signedIn ? props.children : null,
  SignInButton: (props: { children: ReactNode }) => props.children,
  UserButton: () => <button type="button" aria-label="Open user menu" />,
  useAuth: () => ({ getToken: () => new Promise<string | null>(() => {}) }),
}))

describe('Account', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the target titles beside the sign-in check when signed in', () => {
    clerk.signedIn = true

    render(<Account />)

    expect(
      screen.getByRole('heading', { level: 2, name: 'Your profile' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Confirming your sign-in with the service…'),
    ).toBeInTheDocument()
  })

  it('shows the resume after the target titles when signed in', () => {
    clerk.signedIn = true

    render(<Account />)

    const headings = screen
      .getAllByRole('heading', { level: 2 })
      .map((heading) => heading.textContent)
    expect(headings.slice(-2)).toEqual(['Your profile', 'Resume'])
  })

  it('shows no target titles when signed out', () => {
    clerk.signedIn = false

    render(<Account />)

    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Your profile' })).not.toBeInTheDocument()
  })
})
