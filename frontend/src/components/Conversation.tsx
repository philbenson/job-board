import type { Entry } from '../api/interview.ts'
import { SECTION_HEADINGS } from './sectionHeadings.ts'

const SPEAKERS: Record<Exclude<Entry['kind'], 'saved'>, string> = {
  interviewer: 'Interviewer',
  person: 'You',
  notice: 'Job board',
}

type Props = {
  entries: Entry[]
  // The answer the backend has taken but not yet read back, shown last.
  sent: string | null
  // The id the last interviewer line's words carry, so the answer box can
  // name the question by it.
  questionId: string
}

/**
 * The interview's conversation, oldest first, each line's speaker named in
 * words. What was said is shown as text with its line breaks, never parsed,
 * since it comes from the person and the model.
 */
export function Conversation({ entries, sent, questionId }: Props) {
  const question = entries.findLastIndex((entry) => entry.kind === 'interviewer')
  return (
    <ol aria-label="Conversation" className="conversation">
      {entries.map((entry, index) =>
        entry.kind === 'saved' ? (
          // The entries never change once read, only grow, so each one's
          // place names it.
          <li key={index} className="saved">
            Saved to your profile: {SECTION_HEADINGS[entry.section]}
          </li>
        ) : (
          <li key={index}>
            <p className="speaker">{SPEAKERS[entry.kind]}</p>
            <p className="said" id={index === question ? questionId : undefined}>
              {entry.text}
            </p>
          </li>
        ),
      )}
      {sent !== null && (
        <li>
          <p className="speaker">You (sent)</p>
          <p className="said">{sent}</p>
        </li>
      )}
    </ol>
  )
}
