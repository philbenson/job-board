import { Show, SignInButton, UserButton } from '@clerk/react'

/** Clerk's sign-in button when signed out; its user button when signed in. */
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
      </Show>
    </section>
  )
}
