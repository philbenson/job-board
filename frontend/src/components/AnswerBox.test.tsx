import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnswerBox } from './AnswerBox.tsx'

function ignore(): void {}

describe('AnswerBox', () => {
  // The box counts the text it is handed. A textarea hands over `\n` alone,
  // but the backend unifies line breaks in whatever it is sent.
  it('counts a Windows line break as the one character the backend stores, so the answer can be sent at the cap', () => {
    render(
      <AnswerBox text={`${'a'.repeat(3_998)}\r\na`} onText={ignore} held={false} questionId={null} onSend={ignore} />,
    )

    expect(screen.getByLabelText('Your answer')).toHaveAccessibleDescription('4,000 of 4,000 characters')
    expect(screen.getByRole('button', { name: 'Send' })).toHaveAttribute('aria-disabled', 'false')
  })
})
