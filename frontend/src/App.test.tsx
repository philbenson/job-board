import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'

describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('names the app, says what it is for and shows the service status', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => {})),
    )

    render(<App />)

    expect(
      screen.getByRole('heading', { level: 1, name: 'Job board' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/job postings scored against it, best first/),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking the service…',
    )
  })
})
