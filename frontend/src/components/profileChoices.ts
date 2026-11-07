import { STATE_NAMES, type StateCode } from '../api/profile.ts'

/** A value a control sends, with the words it shows for it. */
export type Choice<Value extends string> = readonly [Value, string]

/** Every state the backend takes, by name, in the order of the names. */
export const STATE_CHOICES: readonly Choice<StateCode>[] = (
  Object.entries(STATE_NAMES) as [StateCode, string][]
).toSorted(([, one], [, other]) => one.localeCompare(other, 'en'))

/** Days a week in an office, from one to the backend's full week on site. */
export const DAY_CHOICES: readonly Choice<string>[] = [
  ['1', '1'],
  ['2', '2'],
  ['3', '3'],
  ['4', '4'],
  ['5', '5 (on site)'],
]
