import { Show, SignInButton, UserButton } from '@clerk/react'
import { AccountPanel } from './AccountPanel.tsx'

/**
 * Clerk's sign-in button when signed out; its user button and what the
 * backend made of the sign-in when signed in.
 */
export function Account() {
  return (
    <section aria-label="Account">
      <Show when="signed-out">
        <SignInButton mode="modal">
          <button type="button">Sign in</button>
        </SignInButton>
      </Show>
      <Show when="signed-in">
        <UserButton />
        <AccountPanel />
      </Show>
    </section>
  )
}
