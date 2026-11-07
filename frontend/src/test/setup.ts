import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library unmounts on its own only when the runner exposes global
// hooks; this suite imports them, so each test's render is removed here.
afterEach(() => {
  cleanup()
})
