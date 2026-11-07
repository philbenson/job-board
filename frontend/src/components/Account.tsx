import {
  ClerkFailed,
  ClerkLoading,
  Show,
  SignInButton,
  UserButton,
} from '@clerk/react'
import { AccountPanel } from './AccountPanel.tsx'
import { ProfilePanel } from './ProfilePanel.tsx'

/**
 * Clerk's sign-in button when signed out; its user button, what the backend
 * made of the sign-in, and the person's target titles when signed in. Until
 * Clerk has loaded neither shows, so the area says it is loading, or that
 * Clerk could not load, rather than standing empty.
 */
export function Account() {
  return (
    <section aria-label="Account">
      <ClerkLoading>
        <p>Loading sign-in…</p>
      </ClerkLoading>
      <ClerkFailed>
        <p>Sign-in could not load</p>
      </ClerkFailed>
      <Show when="signed-out">
        <SignInButton mode="modal">
          <button type="button">Sign in</button>
        </SignInButton>
      </Show>
      <Show when="signed-in">
        <UserButton />
        <AccountPanel />
        <ProfilePanel />
      </Show>
    </section>
  )
}
