import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import type { Choice } from './profileChoices.ts'
import { composed } from './profileText.ts'

// Where focus goes after the last item is removed.
const FIRST_INPUT = Symbol('the first input')

// A row's own key: its exact fields. Two stored items can share `keyOf`
// where this browser folds case further than the backend, which kept them
// apart; a key they share would draw one row for both.
function rowKey(item: unknown): string {
  return JSON.stringify(item)
}

/** The second input: typed text, a typed whole number, or a choice. */
export type SecondInput =
  | { kind: 'text'; label: string }
  | { kind: 'number'; label: string }
  | { kind: 'select'; label: string; options: readonly Choice<string>[] }

/** The item two typed values make; why they make none; or nothing to add. */
export type Made<Item> = { item: Item } | { notice: string } | null

type PairsEditorProps<Item> = {
  legend: string
  listLabel: string
  items: readonly Item[]
  /** The list after an Add or a Remove; never called while held. */
  onChange: (next: Item[]) => void
  /** Why an Add was refused, for the part's notice line. */
  onNotice: (notice: string) => void
  held: boolean
  firstLabel: string
  second: SecondInput
  /**
   * The item made from the first part, trimmed, composed and never blank,
   * and the second as typed or chosen.
   */
  itemFrom: (first: string, second: string) => Made<Item>
  /** The key two items share when they are one, as the backend's; for refusing a repeat. */
  keyOf: (item: Item) => string
  /** The item in a few words, for its Remove and for notices. */
  nameOf: (item: Item) => string
  /** The item as listed. */
  shownAs: (item: Item) => string
  cap: number
  /** Many items, as a sentence goes on: "offices". */
  pluralNoun: string
}

/**
 * A list of pairs, such as a city and days a week: two labelled inputs and
 * Add, then each item shown as text with a Remove named for it. An Add is
 * refused, with a notice, for what `itemFrom` refuses, a repeat by `keyOf`,
 * or a list at its cap; an Add with the first part blank does nothing.
 *
 * While held, every control keeps focus but changes nothing, as in the list
 * of texts.
 */
export function PairsEditor<Item>({
  legend,
  listLabel,
  items,
  onChange,
  onNotice,
  held,
  firstLabel,
  second,
  itemFrom,
  keyOf,
  nameOf,
  shownAs,
  cap,
  pluralNoun,
}: PairsEditorProps<Item>) {
  const secondStart = second.kind === 'select' ? (second.options[0]?.[0] ?? '') : ''
  const [first, setFirst] = useState('')
  const [secondValue, setSecondValue] = useState(secondStart)
  // After a Remove, the row key of the item whose Remove takes focus once
  // the list has redrawn, or the first input.
  const focusNext = useRef<string | typeof FIRST_INPUT | null>(null)
  const removeButtons = useRef(new Map<string, HTMLButtonElement>())
  const firstInput = useRef<HTMLInputElement>(null)
  const firstId = useId()
  const secondId = useId()

  useEffect(() => {
    const target = focusNext.current
    focusNext.current = null
    if (target === FIRST_INPUT) {
      firstInput.current?.focus()
    } else if (target !== null) {
      removeButtons.current.get(target)?.focus()
    }
  }, [items])

  function remove(item: Item): void {
    if (held) {
      return
    }
    const at = items.indexOf(item)
    const next = items[at + 1] ?? items[at - 1]
    focusNext.current = next === undefined ? FIRST_INPUT : rowKey(next)
    onChange(items.filter((listed) => listed !== item))
  }

  function add(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (held) {
      return
    }
    const text = composed(first)
    if (text === '') {
      setFirst('')
      return
    }
    const made = itemFrom(text, secondValue)
    if (made === null) {
      return
    }
    if ('notice' in made) {
      onNotice(made.notice)
      return
    }
    const key = keyOf(made.item)
    const existing = items.find((listed) => keyOf(listed) === key)
    if (existing !== undefined) {
      onNotice(`${nameOf(existing)} is already in your list`)
      return
    }
    if (items.length >= cap) {
      onNotice(`You can list at most ${cap} ${pluralNoun}`)
      return
    }
    onChange([...items, made.item])
    setFirst('')
    setSecondValue(secondStart)
  }

  return (
    <fieldset>
      <legend>{legend}</legend>
      {items.length > 0 && (
        <ul aria-label={listLabel}>
          {items.map((item) => {
            const key = rowKey(item)
            return (
              <li key={key}>
                <span>{shownAs(item)}</span>{' '}
                <button
                  type="button"
                  aria-label={`Remove ${nameOf(item)}`}
                  aria-disabled={held}
                  ref={(button) => {
                    if (button === null) {
                      removeButtons.current.delete(key)
                    } else {
                      removeButtons.current.set(key, button)
                    }
                  }}
                  onClick={() => {
                    remove(item)
                  }}
                >
                  Remove
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <form onSubmit={add}>
        <label htmlFor={firstId}>{firstLabel}</label>{' '}
        <input
          id={firstId}
          ref={firstInput}
          type="text"
          value={first}
          readOnly={held}
          aria-disabled={held}
          onChange={(event) => {
            if (!held) {
              setFirst(event.target.value)
            }
          }}
        />{' '}
        <label htmlFor={secondId}>{second.label}</label>{' '}
        {second.kind === 'select' ? (
          <select
            id={secondId}
            value={secondValue}
            aria-disabled={held}
            onChange={(event) => {
              if (!held) {
                setSecondValue(event.target.value)
              }
            }}
          >
            {second.options.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={secondId}
            type="text"
            inputMode={second.kind === 'number' ? 'numeric' : undefined}
            value={secondValue}
            readOnly={held}
            aria-disabled={held}
            onChange={(event) => {
              if (!held) {
                setSecondValue(event.target.value)
              }
            }}
          />
        )}{' '}
        <button type="submit" aria-disabled={held}>
          Add
        </button>
      </form>
    </fieldset>
  )
}
