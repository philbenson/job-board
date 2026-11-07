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
