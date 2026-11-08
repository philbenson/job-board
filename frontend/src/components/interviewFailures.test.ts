import { describe, expect, it } from 'vitest'
import { FAILURE_CODES } from '../api/interview.ts'
import { FAILURE_SENTENCES } from './interviewFailures.ts'

describe('FAILURE_SENTENCES', () => {
  it('says a sentence of its own for every failure code the backend sends', () => {
    const sentences = FAILURE_CODES.map((code) => FAILURE_SENTENCES[code])

    expect(FAILURE_CODES).toHaveLength(16)
    for (const sentence of sentences) {
      expect(sentence).toMatch(/^[A-Z].*\.$/)
    }
    expect(new Set(sentences).size).toBe(sentences.length)
  })
})
