// The profile's caps and longest lengths, each the same as the backend's
// constant named beside it in profile_sections.py. The backend refuses past
// them anyway; checking here too lets the person hear it at once, as they
// add, instead of when they save. Lengths are in characters of the composed
// form, and are checked as an item is added rather than by a length limit on
// the input, which would cut a paste short without a word.

export const MAX_TARGET_TITLES = 20 // MAX_TARGET_TITLES
export const MAX_TITLE_LENGTH = 100 // MAX_TITLE_LENGTH
export const MAX_NEARBY_TITLES = 20 // MAX_NEARBY_TITLES
export const MAX_OFFICES = 20 // MAX_OFFICES
export const MAX_CITY_LENGTH = 100 // MAX_CITY_LENGTH
export const MAX_RELOCATE_FOR = 20 // MAX_RELOCATE_FOR
export const MAX_COMPANY_LENGTH = 100 // MAX_COMPANY_LENGTH
export const MAX_SKILLS = 100 // MAX_SKILLS
export const MAX_SKILL_LENGTH = 60 // MAX_SKILL_LENGTH
export const MAX_GAPS = 20 // MAX_GAPS, for gaps and for trade-offs alike
export const MAX_GAP_LENGTH = 200 // MAX_GAP_LENGTH
export const MAX_INDUSTRIES = 30 // MAX_INDUSTRIES
export const MAX_INDUSTRY_LENGTH = 100 // MAX_INDUSTRY_LENGTH
export const MAX_WATCHED = 30 // MAX_WATCHED
export const MAX_APPLIED = 50 // MAX_APPLIED
export const MAX_RULES = 20 // MAX_RULES
export const MAX_RULE_LENGTH = 300 // MAX_RULE_LENGTH
