/**
 * For each field of a body as sent, what a refusal pointing into it names: a
 * single field's label, or each item's name, in the order sent.
 */
export type Named = Record<string, string | readonly string[]>

/**
 * The backend's rule, followed by the one thing it points at, when it points
 * at something the person can find: an item of a list by its name, or a
 * single field by its label. A rule about a whole list, the whole body or a
 * field the body does not hold is said alone.
 */
export function refusalSentence(
  message: string,
  at: readonly (string | number)[],
  named: Named,
): string {
  const [field, index] = at
  // Its own keys only: the place comes from the answer, so it might name
  // one every object inherits.
  const entry =
    typeof field === 'string' && Object.hasOwn(named, field)
      ? named[field]
      : undefined
  const thing =
    typeof entry === 'string'
      ? entry
      : typeof index === 'number'
        ? entry?.[index]
        : undefined
  return thing === undefined ? message : `${message}: ${thing}`
}
