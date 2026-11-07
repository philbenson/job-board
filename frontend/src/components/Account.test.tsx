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

  it('shows the target titles and the leads beside the sign-in check when signed in', () => {
    clerk.signedIn = true

    render(<Account />)

    expect(
      screen.getByRole('heading', { level: 2, name: 'Target titles' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 2, name: 'Your leads' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Confirming your sign-in with the service…'),
    ).toBeInTheDocument()
  })

  it('shows no target titles and no leads when signed out', () => {
    clerk.signedIn = false

    render(<Account />)

    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Target titles' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Your leads' })).not.toBeInTheDocument()
  })
})
