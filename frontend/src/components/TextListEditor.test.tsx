import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { TextListEditor } from './TextListEditor.tsx'

// The editor as a part uses it: the part holds the list and the notice line.
function Rules({ initial, held = false }: { initial: string[]; held?: boolean }) {
  const [rules, setRules] = useState(initial)
  const [notice, setNotice] = useState('')
  return (
    <>
      <TextListEditor
        items={rules}
        onChange={(next) => {
          setRules(next)
          setNotice('')
        }}
        onNotice={setNotice}
        held={held}
        inputLabel="Add a rule"
        listLabel="Your own rules"
        oneNoun="A rule"
        pluralNoun="rules"
        cap={3}
        maxLength={12}
      />
      <p role="status">{notice}</p>
    </>
  )
}

function shownRules(): string[] {
  const list = screen.queryByRole('list', { name: 'Your own rules' })
  return list === null
    ? []
    : within(list)
        .getAllByRole('listitem')
        .map((item) => item.firstChild?.textContent ?? '')
}

describe('TextListEditor', () => {
  it('speaks of its own noun, cap and longest length', async () => {
    const user = userEvent.setup()
    render(<Rules initial={['No travel', 'No nights']} />)
    const input = screen.getByRole('textbox', { name: 'Add a rule' })

    await user.type(input, 'NO TRAVEL{Enter}')
    expect(screen.getByRole('status')).toHaveTextContent('No travel is already in your list')

    fireEvent.change(input, { target: { value: 'x'.repeat(13) } })
    await user.type(input, '{Enter}')
    expect(screen.getByRole('status')).toHaveTextContent(
      `A rule can be at most 12 characters: ${'x'.repeat(13)}`,
    )

    fireEvent.change(input, { target: { value: 'x'.repeat(12) } })
    await user.type(input, '{Enter}')
    expect(shownRules()).toEqual(['No travel', 'No nights', 'x'.repeat(12)])
    expect(screen.getByRole('status')).toHaveTextContent('')

    await user.type(input, 'No weekends{Enter}')
    expect(shownRules()).toHaveLength(3)
    expect(screen.getByRole('status')).toHaveTextContent('You can list at most 3 rules')
  })

  it('shows an empty list as nothing when it has no words for one', () => {
    render(<Rules initial={[]} />)

    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Add a rule' })).toHaveValue('')
  })

  it('holds every control while held, changing nothing', async () => {
    const user = userEvent.setup()
    render(<Rules initial={['No travel']} held />)
    const input = screen.getByRole('textbox', { name: 'Add a rule' })

    for (const control of [
      input,
      screen.getByRole('button', { name: 'Add' }),
      screen.getByRole('button', { name: 'Remove No travel' }),
    ]) {
      expect(control).toHaveAttribute('aria-disabled', 'true')
      expect(control).not.toBeDisabled()
    }
    await user.type(input, 'No nights{Enter}')
    await user.click(screen.getByRole('button', { name: 'Remove No travel' }))

    expect(shownRules()).toEqual(['No travel'])
    expect(input).toHaveValue('')
  })
})
