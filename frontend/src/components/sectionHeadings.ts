import type { SavedSection } from '../api/interview.ts'

/**
 * Each profile section's heading, as its part shows it and as the interview
 * names a section it saved, so the two never drift apart. Keyed by the
 * sections the interviewer can save, which are the profile's own, so a
 * section the backend adds fails the type check until it has a heading.
 */
export const SECTION_HEADINGS: Record<SavedSection, string> = {
  target_titles: 'Target titles',
  title_range: 'Nearby titles',
  places: 'Places',
  pay: 'Pay',
  skills: 'Skills',
  gaps: 'Gaps and trade-offs',
  deal_breakers: 'Deal-breakers',
  companies: 'Companies',
  pace: 'Pace',
  own_rules: 'Your own rules',
}
