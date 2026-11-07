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
