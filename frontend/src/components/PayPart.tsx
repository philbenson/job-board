import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { WholeNumberField } from './ProfileFields.tsx'
import { ProfilePart } from './ProfilePart.tsx'
import { grouped, wholeNumberFrom } from './profileText.ts'
import { useProfilePart } from './useProfilePart.ts'

type Pay = StoredSection<'/profile/pay'>

const FLOOR = 'Lowest base pay you would take, in US dollars a year'
const ASK = 'Base pay you would ask for, in US dollars a year'

/** The lowest annual base pay the person would take, and what they ask. */
export function PayPart({ stored }: { stored: Pay | null }) {
  const part = useProfilePart(
    '/profile/pay',
    stored,
    'Could not save your pay; your changes are still here',
  )
  const [floor, setFloor] = useState(stored === null ? '' : grouped(stored.floor_usd))
  const [ask, setAsk] = useState(stored === null ? '' : grouped(stored.ask_usd))

  function show(section: Pay): void {
    setFloor(grouped(section.floor_usd))
    setAsk(grouped(section.ask_usd))
  }

  function sendAll(): void {
    if (part.held) {
      return
    }
    const floorUsd = wholeNumberFrom(floor)
    const askUsd = wholeNumberFrom(ask)
    if (floorUsd === 'not whole') {
      part.say('Enter the lowest base pay as a whole number')
    } else if (floorUsd === 'too large') {
      part.say('The lowest base pay is too large')
    } else if (askUsd === 'not whole') {
      part.say('Enter the base pay you would ask for as a whole number')
    } else if (askUsd === 'too large') {
      part.say('The base pay you would ask for is too large')
    } else {
      part.send({ floor_usd: floorUsd, ask_usd: askUsd }, { floor_usd: FLOOR, ask_usd: ASK }, show)
    }
  }

  return (
    <ProfilePart heading="Pay" part={part} onSave={sendAll}>
      <WholeNumberField
        label={FLOOR}
        value={floor}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setFloor(next))
        }}
      />
      <WholeNumberField
        label={ASK}
        value={ask}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setAsk(next))
        }}
      />
    </ProfilePart>
  )
}
