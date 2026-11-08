import {
  ClerkFailed,
  ClerkLoading,
  Show,
  SignInButton,
  UserButton,
} from '@clerk/react'
import { useCallback, useState } from 'react'
import { AccountPanel } from './AccountPanel.tsx'
import { InterviewPanel } from './InterviewPanel.tsx'
import { LeadsPanel } from './LeadsPanel.tsx'
import { ModelKeyPanel } from './ModelKeyPanel.tsx'
import { ProfilePanel } from './ProfilePanel.tsx'
import { ResumePanel } from './ResumePanel.tsx'

/**
 * Clerk's sign-in button when signed out; its user button, what the backend
 * made of the sign-in, the person's model key, their resume, the interview
 * beside their profile, and their leads when signed in. Until Clerk has
 * loaded neither shows, so the area says it is loading, or that Clerk could
 * not load, rather than standing empty.
 *
 * The page counts the changes the key and resume panels report, and the
 * interview reads itself again for each, so what it says is missing stays
 * current without a reload. It counts the interviewer's saves the same way,
 * and the profile reads itself again for each, so they show beside the
 * conversation.
 */
export function Account() {
  const [changes, setChanges] = useState(0)
  const changed = useCallback(() => {
    setChanges((count) => count + 1)
  }, [])
  const [saves, setSaves] = useState(0)
  const saved = useCallback(() => {
    setSaves((count) => count + 1)
  }, [])

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
        <ModelKeyPanel onChange={changed} />
        <ResumePanel onChange={changed} />
        {/* Side by side on a wide window, the conversation first; see index.css. */}
        <div className="interview-area">
          <InterviewPanel changes={changes} onSaved={saved} />
          <ProfilePanel saves={saves} />
        </div>
        <LeadsPanel />
      </Show>
    </section>
  )
}
