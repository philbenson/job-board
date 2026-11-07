import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { composed, lengthOf, repeatKey } from './profileText.ts'

// Where focus goes after the last item is removed.
const INPUT = Symbol('the input')

type TextListEditorProps = {
  items: readonly string[]
  /** The list after an Add or a Remove; never called while held. */
  onChange: (next: string[]) => void
  /** Why an Add was refused, for the part's notice line. */
  onNotice: (notice: string) => void
  held: boolean
  /** The input's label, "Add a nearby title". */
  inputLabel: string
  /** The list's name, "Your nearby titles". */
  listLabel: string
  /** One item, as a sentence starts: "A nearby title". */
  oneNoun: string
  /** One item as its Add names it, after the word: "nearby title". */
  itemNoun: string
  /** Many items, as a sentence goes on: "nearby titles". */
  pluralNoun: string
  cap: number
  maxLength: number
  /** What an empty list says; nothing when not given. */
  emptyText?: string
  /** The id of a condition the input is read with, when the list has one. */
  describedBy?: string
}

/**
 * A list of texts: each shown as text with a Remove named for it, then an
 * input and Add. An Add is refused, with a notice, for a text past the
 * longest length, a repeat within the list, or a list at its cap.
 *
 * While held, every control keeps focus but changes nothing: they are held
 * with aria-disabled and guarded handlers rather than disabled, which would
 * drop keyboard focus to the page.
 */
export function TextListEditor({
  items,
  onChange,
  onNotice,
  held,
  inputLabel,
  listLabel,
  oneNoun,
  itemNoun,
  pluralNoun,
  cap,
  maxLength,
  emptyText,
  describedBy,
}: TextListEditorProps) {
  const [draft, setDraft] = useState('')
  // After a Remove, the control that takes focus once the list has redrawn:
  // an item's Remove button, or the input.
  const focusNext = useRef<string | typeof INPUT | null>(null)
  const removeButtons = useRef(new Map<string, HTMLButtonElement>())
  const input = useRef<HTMLInputElement>(null)
  const inputId = useId()

  useEffect(() => {
    const target = focusNext.current
    focusNext.current = null
    if (target === INPUT) {
      input.current?.focus()
    } else if (target !== null) {
      removeButtons.current.get(target)?.focus()
    }
  }, [items])

  /**
   * Removes `item` and moves focus to the next item's Remove button, else
   * the one before, else the input, so a keyboard stays where it was working.
   */
  function remove(item: string): void {
    if (held) {
      return
    }
    const at = items.indexOf(item)
    focusNext.current = items[at + 1] ?? items[at - 1] ?? INPUT
    onChange(items.filter((listed) => listed !== item))
  }

  function add(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (held) {
      return
    }
    const text = composed(draft)
    if (text === '') {
      setDraft('')
      return
    }
    if (lengthOf(text) > maxLength) {
      onNotice(`${oneNoun} can be at most ${maxLength} characters: ${text}`)
      return
    }
    const key = repeatKey(text)
    const existing = items.find((listed) => repeatKey(listed) === key)
    if (existing !== undefined) {
      onNotice(`${existing} is already in your list`)
      return
    }
    if (items.length >= cap) {
      onNotice(`You can list at most ${cap} ${pluralNoun}`)
      return
    }
    onChange([...items, text])
    setDraft('')
  }

  return (
    <>
      {items.length === 0 ? (
        emptyText !== undefined && <p>{emptyText}</p>
      ) : (
        <ul aria-label={listLabel}>
          {items.map((item) => (
            <li key={item}>
              <span>{item}</span>{' '}
              <button
                type="button"
                aria-label={`Remove ${item}`}
                aria-disabled={held}
                ref={(button) => {
                  if (button === null) {
                    removeButtons.current.delete(item)
                  } else {
                    removeButtons.current.set(item, button)
                  }
                }}
                onClick={() => {
                  remove(item)
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={add}>
        <label htmlFor={inputId}>{inputLabel}</label>{' '}
        <input
          id={inputId}
          ref={input}
          type="text"
          value={draft}
          readOnly={held}
          aria-disabled={held}
          aria-describedby={describedBy}
          onChange={(event) => {
            if (!held) {
              setDraft(event.target.value)
            }
          }}
        />{' '}
        {/* Named for its item, after the word it shows, as each part's Save. */}
        <button type="submit" aria-disabled={held}>
          Add{' '}
          <span className="visually-hidden">{itemNoun}</span>
        </button>
      </form>
    </>
  )
}
