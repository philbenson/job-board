import { describe, expect, it } from 'vitest'
import { SAVED_SECTIONS } from '../api/interview.ts'
import { SECTION_HEADINGS } from './sectionHeadings.ts'

describe('SECTION_HEADINGS', () => {
  it('heads every section the interviewer can save, each apart from the others', () => {
    const headings = SAVED_SECTIONS.map((section) => SECTION_HEADINGS[section])

    expect(SAVED_SECTIONS).toHaveLength(10)
    for (const heading of headings) {
      expect(heading).toMatch(/\S/)
    }
    expect(new Set(headings).size).toBe(headings.length)
  })
})
