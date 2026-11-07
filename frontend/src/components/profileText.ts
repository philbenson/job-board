/**
 * The text as the backend stores it, trimmed and composed (NFC), so a letter
 * and its accent count as one character.
 */
export function composed(text: string): string {
  return text.trim().normalize('NFC')
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
