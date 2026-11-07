import { useId } from 'react'
import type { Choice } from './profileChoices.ts'

// The single fields of a part. Each is held like the lists: aria-disabled
// and a guarded handler, never disabled, which would drop keyboard focus. A
// held box or list is drawn again from its value, unchanged.

type FieldProps<Value> = {
  label: string
  held: boolean
  onChange: (next: Value) => void
}

/** A yes-or-no, as a check box. */
export function YesNoField({
  label,
  checked,
  held,
  onChange,
}: FieldProps<boolean> & { checked: boolean }) {
  return (
    <label>
      <input
        type="checkbox"
        checked={checked}
        aria-disabled={held}
        onChange={(event) => {
          if (!held) {
            onChange(event.target.checked)
          }
        }}
      />
      {label}
    </label>
  )
}

/**
 * A whole number, typed as text that may hold commas: a number input would
 * refuse the commas, and the page says itself what is not a whole number.
 */
export function WholeNumberField({
  label,
  value,
  held,
  onChange,
}: FieldProps<string> & { value: string }) {
  const id = useId()
  return (
    <p>
      <label htmlFor={id}>{label}</label>{' '}
      <input
        id={id}
        type="text"
        inputMode="numeric"
        value={value}
        readOnly={held}
        aria-disabled={held}
        onChange={(event) => {
          if (!held) {
            onChange(event.target.value)
          }
        }}
      />
    </p>
  )
}

/** One of a few choices, as a select. */
export function ChoiceField({
  label,
  options,
  value,
  held,
  onChange,
}: FieldProps<string> & { value: string; options: readonly Choice<string>[] }) {
  const id = useId()
  return (
    <p>
      <label htmlFor={id}>{label}</label>{' '}
      <select
        id={id}
        value={value}
        aria-disabled={held}
        onChange={(event) => {
          if (!held) {
            onChange(event.target.value)
          }
        }}
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </p>
  )
}
