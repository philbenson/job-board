import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, onTestFinished, vi } from 'vitest'
import { PairsEditor } from './PairsEditor.tsx'
import { repeatKey, wholeNumberFrom } from './profileText.ts'

type Office = { city: string; days_a_week: number }

// The editor as the places part uses it, with a cap of two to keep the
// fixture short.
function Offices({
  initial,
  held = false,
  typedDays = false,
}: {
  initial: Office[]
  held?: boolean
  // Days typed as a number rather than chosen, to show a pair refused.
  typedDays?: boolean
}) {
  const [offices, setOffices] = useState(initial)
  const [notice, setNotice] = useState('')
  return (
    <>
      <PairsEditor
        legend="Offices you would go into"
        listLabel="Your offices"
        items={offices}
        onChange={(next) => {
          setOffices(next)
          setNotice('')
        }}
        onNotice={setNotice}
        held={held}
        firstLabel="City"
        itemNoun="office"
        second={
          typedDays
            ? { kind: 'number', label: 'Days a week in the office' }
            : {
                kind: 'select',
                label: 'Days a week in the office',
                options: [
                  ['1', '1'],
                  ['5', '5 (on site)'],
                ],
              }
        }
        itemFrom={(city, days) => {
          const days_a_week = wholeNumberFrom(days)
          return days_a_week === null
            ? { notice: 'Enter days a week as a whole number' }
            : { item: { city, days_a_week } }
        }}
        keyOf={(office) => repeatKey(office.city)}
        nameOf={(office) => office.city}
        shownAs={(office) => `${office.city}, ${office.days_a_week} days a week`}
        cap={2}
        pluralNoun="offices"
      />
      <p role="status">{notice}</p>
    </>
  )
}

function shown(): string[] {
  const group = screen.getByRole('group', { name: 'Offices you would go into' })
  const list = within(group).queryByRole('list')
  return list === null
    ? []
    : within(list)
        .getAllByRole('listitem')
        .map((item) => item.firstChild?.textContent ?? '')
}

describe('PairsEditor', () => {
  it('adds a pair from its two labelled inputs, trimmed, then clears them', async () => {
    const user = userEvent.setup()
    render(<Offices initial={[]} />)

    await user.type(screen.getByRole('textbox', { name: 'City' }), '  Boston ')
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Days a week in the office' }),
      '5 (on site)',
    )
    await user.click(screen.getByRole('button', { name: 'Add office' }))

    expect(shown()).toEqual(['Boston, 5 days a week'])
    expect(screen.getByRole('textbox', { name: 'City' })).toHaveValue('')
    expect(screen.getByRole('combobox', { name: 'Days a week in the office' })).toHaveValue('1')
  })

  it('ignores an Add with the first part blank', async () => {
    const user = userEvent.setup()
    render(<Offices initial={[]} />)

    await user.type(screen.getByRole('textbox', { name: 'City' }), '   {Enter}')

    expect(shown()).toEqual([])
    expect(screen.getByRole('status')).toHaveTextContent('')
  })

  it('refuses a repeat by its key and a pair past the cap, saying so', async () => {
    const user = userEvent.setup()
    render(<Offices initial={[{ city: 'Boston', days_a_week: 2 }]} />)
    const city = screen.getByRole('textbox', { name: 'City' })

    await user.type(city, 'BOSTON{Enter}')
    expect(screen.getByRole('status')).toHaveTextContent('Boston is already in your list')
    expect(shown()).toEqual(['Boston, 2 days a week'])

    await user.clear(city)
    await user.type(city, 'Chicago{Enter}')
    await user.type(city, 'Denver{Enter}')
    expect(shown()).toEqual(['Boston, 2 days a week', 'Chicago, 1 days a week'])
    expect(screen.getByRole('status')).toHaveTextContent('You can list at most 2 offices')
  })

  it('says why the typed pair makes no item, keeping what was typed', async () => {
    const user = userEvent.setup()
    render(<Offices initial={[]} typedDays />)
    const days = screen.getByRole('textbox', { name: 'Days a week in the office' })

    await user.type(screen.getByRole('textbox', { name: 'City' }), 'Boston')
    await user.type(days, '2.5{Enter}')

    expect(shown()).toEqual([])
    expect(screen.getByRole('status')).toHaveTextContent('Enter days a week as a whole number')
    expect(days).toHaveValue('2.5')
    expect(days).toHaveAttribute('inputmode', 'numeric')
  })

  it('names each Remove for its item and moves focus to the next, else the one before, else the first input', async () => {
    const user = userEvent.setup()
    render(
      <Offices
        initial={[
          { city: 'Boston', days_a_week: 1 },
          { city: 'Chicago', days_a_week: 2 },
        ]}
      />,
    )

    screen.getByRole('button', { name: 'Remove Boston' }).focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('button', { name: 'Remove Chicago' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('textbox', { name: 'City' })).toHaveFocus()
    expect(shown()).toEqual([])
  })

  it('holds every control while held, changing nothing', async () => {
    const user = userEvent.setup()
    render(<Offices initial={[{ city: 'Boston', days_a_week: 1 }]} held />)

    for (const control of [
      screen.getByRole('textbox', { name: 'City' }),
      screen.getByRole('combobox', { name: 'Days a week in the office' }),
      screen.getByRole('button', { name: 'Add office' }),
      screen.getByRole('button', { name: 'Remove Boston' }),
    ]) {
      expect(control).toHaveAttribute('aria-disabled', 'true')
    }
    await user.type(screen.getByRole('textbox', { name: 'City' }), 'Chicago{Enter}')
    await user.click(screen.getByRole('button', { name: 'Remove Boston' }))

    expect(shown()).toEqual(['Boston, 1 days a week'])
  })

  it('adds nothing typed or chosen before the hold, and changes no choice, while held', async () => {
    const user = userEvent.setup()
    const boston = [{ city: 'Boston', days_a_week: 1 }]
    const { rerender } = render(<Offices initial={boston} />)
    const city = screen.getByRole('textbox', { name: 'City' })
    const days = screen.getByRole('combobox', { name: 'Days a week in the office' })
    await user.type(city, 'Chicago')
    await user.selectOptions(days, '5 (on site)')

    rerender(<Offices initial={boston} held />)
    await user.click(screen.getByRole('button', { name: 'Add office' }))
    await user.type(city, '{Enter}')
    await user.selectOptions(days, '1')

    expect(shown()).toEqual(['Boston, 1 days a week'])
    expect(city).toHaveValue('Chicago')
    expect(days).toHaveValue('5')
  })

  it('keeps two stored items its key joins as two rows, each its own Remove', async () => {
    const user = userEvent.setup()
    // React reports two rows sharing a key on the console.
    const reported = vi.spyOn(console, 'error').mockImplementation(() => {})
    onTestFinished(() => {
      reported.mockRestore()
    })
    // Two cities the backend's fold keeps apart and this key joins, as a
    // browser on a newer Unicode than the backend's can.
    render(
      <Offices
        initial={[
          { city: 'Chicago', days_a_week: 2 },
          { city: 'Boston', days_a_week: 1 },
          { city: 'BOSTON', days_a_week: 5 },
        ]}
      />,
    )

    screen.getByRole('button', { name: 'Remove Chicago' }).focus()
    await user.keyboard('{Enter}')

    expect(shown()).toEqual(['Boston, 1 days a week', 'BOSTON, 5 days a week'])
    expect(screen.getByRole('button', { name: 'Remove Boston' })).toHaveFocus()
    expect(reported).not.toHaveBeenCalled()
  })
})
