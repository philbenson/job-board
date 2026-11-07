/** A time as the resume's screens write it: in the browser's own locale and time zone. */
export function timeOf(when: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(when)
}
