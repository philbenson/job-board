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

/** A profile whose every section has been saved, so none is null. */
export type FullProfile = {
  [Key in keyof ProfileBody]: NonNullable<ProfileBody[Key]>
}

/** A profile with every section saved, each holding something. */
export function fullProfile(): FullProfile {
  return {
    target_titles: ['Data Analyst'],
    title_range: { nearby_titles: ['Data Scientist'], lower_level_ok: true },
    places: {
      remote_ok: true,
      offices: [{ city: 'Boston', days_a_week: 3 }],
      states: ['MA', 'NY'],
      will_relocate: false,
      relocate_for: ['Example Corp'],
    },
    pay: { floor_usd: 90_000, ask_usd: 120_000 },
    skills: { skills: [{ name: 'Python', years: 5 }] },
    gaps: { apply_with: ['No degree'], trade_offs: ['A longer commute'] },
    deal_breakers: {
      industries: ['Gambling'],
      company_sizes: ['1-10', '10001+'],
      no_agencies: true,
    },
    companies: {
      watch: ['Example Corp'],
      applied: [{ company: 'Example Corp', title: 'Data Analyst' }],
    },
    pace: { leads_per_day: 10, brief_from_score: 4 },
    own_rules: { rules: ['No on-call rota'] },
  }
}
