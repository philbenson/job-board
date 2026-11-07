import type { ProfileBody } from '../api/profile.ts'

/**
 * The profile the backend answers for someone who has saved these target
 * titles and no other section: every other section is null until saved.
 */
export function profileWith(titles: string[]): ProfileBody {
  return {
    target_titles: titles,
    title_range: null,
    places: null,
    pay: null,
    skills: null,
    gaps: null,
    deal_breakers: null,
    companies: null,
    pace: null,
    own_rules: null,
  }
}
