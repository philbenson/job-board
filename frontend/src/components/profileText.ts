// Whitespace and the invisible format characters, which show nothing at an
// end.
const TRIMS_AWAY = /^[\s\p{Cf}]$/u

// The separators the backend's Python counts as whitespace and `\s` does not.
const ALSO_WHITESPACE = new Set(['\u001C', '\u001D', '\u001E', '\u001F', '\u0085'])

// The embeddings, overrides and isolates: format characters the backend
// keeps at an end so as to refuse them, since dropping one would change how
// the rest of the text shows.
const DIRECTION_CONTROL = /^[‪-‮⁦-⁩]$/u

function trimsAway(character: string): boolean {
  return (
    ALSO_WHITESPACE.has(character) ||
    (TRIMS_AWAY.test(character) && !DIRECTION_CONTROL.test(character))
  )
}

/**
 * The text as the backend stores it: trimmed of whitespace and invisible
 * format characters at both ends, then composed (NFC), so a letter and its
 * accent count as one character.
 */
export function composed(text: string): string {
  const characters = [...text]
  let start = 0
  let end = characters.length
  while (start < end && trimsAway(characters[start])) {
    start += 1
  }
  while (end > start && trimsAway(characters[end - 1])) {
    end -= 1
  }
  return characters.slice(start, end).join('').normalize('NFC')
}

/** The length the backend counts: code points, not UTF-16 units. */
export function lengthOf(text: string): number {
  return [...text].length
}

/**
 * The key two texts share when they read as one item. The backend is the
 * authority on repeats: it folds case more fully than this ("Straße" and
 * "STRASSE" are one item there, two here), may drop a repeat this check let
 * through, and the page then shows its list.
 */
export function repeatKey(text: string): string {
  return text.normalize('NFC').toLowerCase()
}

/**
 * The whole number typed, with any commas dropped; null when it is blank or
 * not a whole number. Range is the backend's to check.
 */
export function wholeNumberFrom(typed: string): number | null {
  const digits = typed.trim().replaceAll(',', '')
  if (!/^\d+$/.test(digits)) {
    return null
  }
  const number = Number(digits)
  // Past this a number loses digits, and the backend would read another one.
  return Number.isSafeInteger(number) ? number : null
}

/** A stored amount as a person reads it, its thousands grouped: "120,000". */
export function grouped(amount: number): string {
  return amount.toLocaleString('en-US')
}
