import { useId, type ReactNode } from 'react'
import type { SectionRoute } from '../api/profile.ts'
import type { ProfilePart as Part } from './useProfilePart.ts'

type ProfilePartProps = {
  heading: string
  part: Pick<Part<SectionRoute>, 'answered' | 'held' | 'notice' | 'saveLine'>
  /** Checks what the page can, then sends the part's body. */
  onSave: () => void
  children: ReactNode
}

/**
 * One part of the profile: its heading, whether it has been answered, its
 * editors, and its own Save with its two lines.
 */
export function ProfilePart({ heading, part, onSave, children }: ProfilePartProps) {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId}>
      <h3 id={headingId}>{heading}</h3>
      {!part.answered && <p>Not answered yet.</p>}
      {children}
      {/* Both status lines stay on the page and change their words, which
          is what a screen reader announces. */}
      <p role="status">{part.notice}</p>
      <button type="button" aria-disabled={part.held} onClick={onSave}>
        Save
      </button>
      <p role="status">{part.saveLine}</p>
    </section>
  )
}
