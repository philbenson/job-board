import { useState } from 'react'
import { STATE_NAMES, type StateCode, type StoredSection } from '../api/profile.ts'
import { ChoiceSet } from './ChoiceSet.tsx'
import { PairsEditor } from './PairsEditor.tsx'
import { DAY_CHOICES, STATE_CHOICES } from './profileChoices.ts'
import { YesNoField } from './ProfileFields.tsx'
import {
  MAX_CITY_LENGTH,
  MAX_COMPANY_LENGTH,
  MAX_OFFICES,
  MAX_RELOCATE_FOR,
} from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { lengthOf, repeatKey } from './profileText.ts'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

type Places = StoredSection<'/profile/places'>
type Office = Places['offices'][number]

const REMOTE = 'A fully remote role is fine'
const RELOCATE = 'I would move for a role'
const DAYS_ON_SITE = 5 // the backend's DAYS_ON_SITE: a full week in the office

function officeShown({ city, days_a_week: days }: Office): string {
  const often = `${days} ${days === 1 ? 'day' : 'days'} a week`
  return `${city}, ${often}${days === DAYS_ON_SITE ? ' (on site)' : ''}`
}

/** Remote, offices by city, the states worked from, and moving. */
export function PlacesPart({ stored }: { stored: Places | null }) {
  const part = useProfilePart(
    '/profile/places',
    stored,
    'Could not save your places; your changes are still here',
  )
  const [remoteOk, setRemoteOk] = useState(stored?.remote_ok ?? false)
  const [offices, setOffices] = useState(stored?.offices ?? [])
  const [states, setStates] = useState<StateCode[]>(stored?.states ?? [])
  const [willRelocate, setWillRelocate] = useState(stored?.will_relocate ?? false)
  const [relocateFor, setRelocateFor] = useState(stored?.relocate_for ?? [])

  function show(section: Places): void {
    setRemoteOk(section.remote_ok)
    setOffices(section.offices)
    setStates(section.states)
    setWillRelocate(section.will_relocate)
    setRelocateFor(section.relocate_for)
  }

  return (
    <ProfilePart
      heading="Places"
      part={part}
      onSave={() => {
        part.send(
          {
            remote_ok: remoteOk,
            offices,
            states,
            will_relocate: willRelocate,
            relocate_for: relocateFor,
          },
          {
            remote_ok: REMOTE,
            offices: offices.map((office) => office.city),
            states: states.map((code) => STATE_NAMES[code]),
            will_relocate: RELOCATE,
            relocate_for: relocateFor,
          },
          show,
        )
      }}
    >
      <YesNoField
        label={REMOTE}
        checked={remoteOk}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setRemoteOk(next))
        }}
      />
      <PairsEditor
        legend="Offices you would go into"
        listLabel="Your offices"
        items={offices}
        onChange={(next) => {
          part.edit(() => setOffices(next))
        }}
        onNotice={part.say}
        held={part.held}
        firstLabel="City"
        second={{ kind: 'select', label: 'Days a week in the office', options: DAY_CHOICES }}
        itemFrom={(city, days) =>
          lengthOf(city) > MAX_CITY_LENGTH
            ? { notice: `A city can be at most ${MAX_CITY_LENGTH} characters: ${city}` }
            : { item: { city, days_a_week: Number(days) } }
        }
        keyOf={(office) => repeatKey(office.city)}
        nameOf={(office) => office.city}
        shownAs={officeShown}
        cap={MAX_OFFICES}
        pluralNoun="offices"
      />
      <ChoiceSet
        legend="States you can work from"
        choices={STATE_CHOICES}
        selected={states}
        onChange={(next) => {
          part.edit(() => setStates(next))
        }}
        held={part.held}
      />
      <YesNoField
        label={RELOCATE}
        checked={willRelocate}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setWillRelocate(next))
        }}
      />
      <p>Only if you would not move otherwise</p>
      <TextListEditor
        items={relocateFor}
        onChange={(next) => {
          part.edit(() => setRelocateFor(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a company you would move for"
        listLabel="Companies you would move for"
        oneNoun="A company"
        pluralNoun="companies you would move for"
        cap={MAX_RELOCATE_FOR}
        maxLength={MAX_COMPANY_LENGTH}
      />
    </ProfilePart>
  )
}
