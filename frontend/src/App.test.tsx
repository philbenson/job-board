import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App.tsx'

describe('App', () => {
  it('names the app and says what it is for', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', { level: 1, name: 'Job board' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/job postings scored against it, best first/),
    ).toBeInTheDocument()
  })
})
