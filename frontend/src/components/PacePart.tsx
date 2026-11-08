import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { BRIEF_CHOICES } from './profileChoices.ts'
import { ChoiceField, WholeNumberField } from './ProfileFields.tsx'
import { ProfilePart } from './ProfilePart.tsx'
import { wholeNumberFrom } from './profileText.ts'
import { SECTION_HEADINGS } from './sectionHeadings.ts'
import { useProfilePart } from './useProfilePart.ts'

type Pace = StoredSection<'/profile/pace'>

const LEADS = 'Leads a day'
const BRIEF = 'Write a brief for postings scored at least'

// The brief's choice as the select holds it: no briefs is the empty value.
function briefChoice(score: number | null): string {
  return score === null ? '' : String(score)
}

/** How many postings a day, and the lowest score that gets a brief. */
export function PacePart({ stored }: { stored: Pace | null }) {
  const part = useProfilePart(
    '/profile/pace',
    stored,
    'Could not save your pace; your changes are still here',
  )
  const [leads, setLeads] = useState(stored === null ? '' : String(stored.leads_per_day))
  const [brief, setBrief] = useState(briefChoice(stored?.brief_from_score ?? null))

  function show(section: Pace): void {
    setLeads(String(section.leads_per_day))
    setBrief(briefChoice(section.brief_from_score))
  }

  function sendAll(): void {
    if (part.held) {
      return
    }
    const leadsPerDay = wholeNumberFrom(leads)
    if (leadsPerDay === 'not whole') {
      part.say('Enter leads a day as a whole number')
      return
    }
    if (leadsPerDay === 'too large') {
      part.say('Leads a day is too large')
      return
    }
    part.send(
      { leads_per_day: leadsPerDay, brief_from_score: brief === '' ? null : Number(brief) },
      { leads_per_day: LEADS, brief_from_score: BRIEF },
      show,
    )
  }

  return (
    <ProfilePart heading={SECTION_HEADINGS.pace} part={part} onSave={sendAll}>
      <WholeNumberField
        label={LEADS}
        value={leads}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setLeads(next))
        }}
      />
      <ChoiceField
        label={BRIEF}
        options={BRIEF_CHOICES}
        value={brief}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setBrief(next))
        }}
      />
    </ProfilePart>
  )
}
