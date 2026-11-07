import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { STATE_NAMES, type StateCode } from '../api/profile.ts'
import { ChoiceSet } from './ChoiceSet.tsx'
import { ChoiceField, WholeNumberField, YesNoField } from './ProfileFields.tsx'
import { STATE_CHOICES } from './profileChoices.ts'
import { wholeNumberFrom } from './profileText.ts'

function States({ initial, held = false }: { initial: StateCode[]; held?: boolean }) {
  const [states, setStates] = useState(initial)
  return (
    <>
      <ChoiceSet
        legend="States you can work from"
        choices={STATE_CHOICES}
        selected={states}
        onChange={setStates}
        held={held}
      />
      <output>{states.join(' ')}</output>
    </>
  )
}

describe('ChoiceSet', () => {
  it('names its group by its legend and offers every state by name, in the order of the names', () => {
    render(<States initial={[]} />)

    const group = screen.getByRole('group', { name: 'States you can work from' })
    const names = within(group)
      .getAllByRole('checkbox')
      .map((box) => box.closest('label')?.textContent)
    const expected = Object.values(STATE_NAMES).toSorted((a, b) => a.localeCompare(b))
    expect(names).toEqual(expected)
    expect(names).toHaveLength(51)
    expect(names.slice(0, 3)).toEqual(['Alabama', 'Alaska', 'Arizona'])
  })

  it('checks what is chosen and adds or drops a choice as it is ticked', async () => {
    const user = userEvent.setup()
    render(<States initial={['NY']} />)

    expect(screen.getByRole('checkbox', { name: 'New York' })).toBeChecked()
    await user.click(screen.getByRole('checkbox', { name: 'Maine' }))
    await user.click(screen.getByRole('checkbox', { name: 'New York' }))

    expect(screen.getByRole('status')).toHaveTextContent('ME')
    expect(screen.getByRole('checkbox', { name: 'New York' })).not.toBeChecked()
  })

  it('holds its boxes while held, changing nothing', async () => {
    const user = userEvent.setup()
    render(<States initial={['NY']} held />)
    const box = screen.getByRole('checkbox', { name: 'Maine' })

    expect(box).toHaveAttribute('aria-disabled', 'true')
    await user.click(box)

    expect(box).not.toBeChecked()
    expect(screen.getByRole('status')).toHaveTextContent('NY')
  })
})

describe('the single fields', () => {
  it('reads a whole number with commas dropped, and nothing else as one', () => {
    expect(wholeNumberFrom('120,000')).toBe(120_000)
    expect(wholeNumberFrom(' 7 ')).toBe(7)
    expect(wholeNumberFrom('0')).toBe(0)
    for (const typed of ['', '  ', '1.5', '-3', '1e5', '12 000', 'ten']) {
      expect(wholeNumberFrom(typed), typed).toBe('not whole')
    }
  })

  it('tells a whole number too large to send exactly from one that is not whole', () => {
    expect(wholeNumberFrom('9,007,199,254,740,991')).toBe(Number.MAX_SAFE_INTEGER)
    for (const typed of ['9007199254740992', '99999999999999999999']) {
      expect(wholeNumberFrom(typed), typed).toBe('too large')
    }
  })

  it('offers a number as text a keyboard of digits can fill, and holds it while held', async () => {
    function Floor({ held }: { held: boolean }) {
      const [typed, setTyped] = useState('')
      return <WholeNumberField label="Leads a day" value={typed} onChange={setTyped} held={held} />
    }
    const user = userEvent.setup()
    const { rerender } = render(<Floor held={false} />)
    const input = screen.getByRole('textbox', { name: 'Leads a day' })

    expect(input).toHaveAttribute('inputmode', 'numeric')
    await user.type(input, '12')
    expect(input).toHaveValue('12')

    rerender(<Floor held />)
    await user.type(input, '3')
    expect(input).toHaveValue('12')
    expect(input).toHaveAttribute('aria-disabled', 'true')
  })

  it('ticks a yes-or-no, and holds it while held', async () => {
    function Remote({ held }: { held: boolean }) {
      const [yes, setYes] = useState(false)
      return (
        <YesNoField label="A fully remote role is fine" checked={yes} onChange={setYes} held={held} />
      )
    }
    const user = userEvent.setup()
    const { rerender } = render(<Remote held={false} />)
    const box = screen.getByRole('checkbox', { name: 'A fully remote role is fine' })

    await user.click(box)
    expect(box).toBeChecked()
    rerender(<Remote held />)
    await user.click(box)
    expect(box).toBeChecked()
    expect(box).toHaveAttribute('aria-disabled', 'true')
  })

  it('chooses from a list, and holds it while held', async () => {
    function Score({ held }: { held: boolean }) {
      const [score, setScore] = useState('')
      return (
        <ChoiceField
          label="Write a brief for postings scored at least"
          options={[
            ['', 'No briefs'],
            ['4', '4'],
          ]}
          value={score}
          onChange={setScore}
          held={held}
        />
      )
    }
    const user = userEvent.setup()
    const { rerender } = render(<Score held={false} />)
    const select = screen.getByRole('combobox', { name: 'Write a brief for postings scored at least' })

    expect(select).toHaveValue('')
    await user.selectOptions(select, '4')
    expect(select).toHaveValue('4')
    rerender(<Score held />)
    await user.selectOptions(select, 'No briefs')
    expect(select).toHaveValue('4')
    expect(select).toHaveAttribute('aria-disabled', 'true')
  })
})
