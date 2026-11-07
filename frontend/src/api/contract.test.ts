import { describe, expect, it } from 'vitest'

// Every module in this folder as source text, except tests and the generated
// file itself: only the clients that talk to the backend are held to this.
const modules = import.meta.glob<string>(
  ['./*.ts', '!./*.test.ts', '!./schema.ts'],
  { query: '?raw', import: 'default', eager: true },
)

const CALLS_FETCH = /\bfetch\(/
const IMPORTS_SCHEMA = /from\s+['"]\.\/schema(\.ts)?['"]/

describe('API clients', () => {
  it('reads the modules in this folder', () => {
    // Without this, a glob that matched nothing would pass the check below.
    expect(Object.keys(modules)).toContain('./health.ts')
  })

  it('type every module that calls the backend from the generated schema', () => {
    const untyped = Object.entries(modules)
      .filter(
        ([, source]) => CALLS_FETCH.test(source) && !IMPORTS_SCHEMA.test(source),
      )
      .map(([path]) => path)

    expect(
      untyped,
      'these call fetch without importing the generated types from ./schema.ts',
    ).toEqual([])
  })
})
