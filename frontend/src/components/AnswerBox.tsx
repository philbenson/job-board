import { useId } from 'react'

// The backend holds the same cap and refuses past it.
export const MAX_ANSWER_LENGTH = 4_000

type Props = {
  text: string
  onText: (text: string) => void
  // Held while the answer is out and while the turn it started runs.
  held: boolean
  // The id of the question's words, when the interview waits on one.
  questionId: string | null
  onSend: () => void
}

/**
 * The box the person answers the interviewer's question in, with Send. Enter
 * adds a line, as in the resume's text box; Send sends. The box describes
 * itself by the question and its count, which is in code points, as the
 * backend counts. Send is held while the box shows nothing but spaces or is
 * past the cap.
 *
 * Held, the box is read-only and ignores input, and Send does nothing, so
 * focus stays where it is and what the box shows is what was sent.
 */
export function AnswerBox({ text, onText, held, questionId, onSend }: Props) {
  const boxId = useId()
  const countId = useId()
  const length = [...text].length
  const sendable = !held && /\S/.test(text) && length <= MAX_ANSWER_LENGTH
  return (
    <div className="answer">
      <label htmlFor={boxId}>Your answer</label>
      <textarea
        id={boxId}
        value={text}
        rows={6}
        aria-describedby={questionId === null ? countId : `${questionId} ${countId}`}
        readOnly={held}
        aria-disabled={held}
        onChange={(event) => {
          if (!held) {
            onText(event.target.value)
          }
        }}
      />
      <p id={countId}>
        {length.toLocaleString('en-US')} of {MAX_ANSWER_LENGTH.toLocaleString('en-US')} characters
      </p>
      <button
        type="button"
        aria-disabled={!sendable}
        onClick={() => {
          if (sendable) {
            onSend()
          }
        }}
      >
        Send
      </button>
    </div>
  )
}
