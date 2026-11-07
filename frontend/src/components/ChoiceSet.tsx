import type { Choice } from './profileChoices.ts'

type ChoiceSetProps<Value extends string> = {
  legend: string
  choices: readonly Choice<Value>[]
  selected: readonly Value[]
  /** The choices ticked after a change; never called while held. */
  onChange: (next: Value[]) => void
  held: boolean
}

/**
 * A set of check boxes in a fieldset, one per choice, each labelled by its
 * words. A choice ticked is added at the end; one unticked is dropped.
 */
export function ChoiceSet<Value extends string>({
  legend,
  choices,
  selected,
  onChange,
  held,
}: ChoiceSetProps<Value>) {
  return (
    <fieldset>
      <legend>{legend}</legend>
      {choices.map(([value, label]) => (
        <label key={value}>
          <input
            type="checkbox"
            checked={selected.includes(value)}
            aria-disabled={held}
            onChange={(event) => {
              // A held box is drawn again from `selected`, unchanged.
              if (held) {
                return
              }
              onChange(
                event.target.checked
                  ? [...selected, value]
                  : selected.filter((chosen) => chosen !== value),
              )
            }}
          />
          {label}
        </label>
      ))}
    </fieldset>
  )
}
