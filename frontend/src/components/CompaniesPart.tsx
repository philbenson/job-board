import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { PairsEditor } from './PairsEditor.tsx'
import {
  MAX_APPLIED,
  MAX_COMPANY_LENGTH,
  MAX_TITLE_LENGTH,
  MAX_WATCHED,
} from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { composed, lengthOf, repeatKey } from './profileText.ts'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

type Companies = StoredSection<'/profile/companies'>
type Application = Companies['applied'][number]

function jobShown({ company, title }: Application): string {
  return `${title} at ${company}`
}

// One job is the same company with the same title, as the backend folds
// both; the same company with another title is another job.
function sameJob({ company, title }: Application): string {
  return JSON.stringify([repeatKey(company), repeatKey(title)])
}

/** Companies to watch, and the jobs already applied to. */
export function CompaniesPart({ stored }: { stored: Companies | null }) {
  const part = useProfilePart(
    '/profile/companies',
    stored,
    'Could not save your companies; your changes are still here',
  )
  const [watch, setWatch] = useState(stored?.watch ?? [])
  const [applied, setApplied] = useState(stored?.applied ?? [])

  function show(section: Companies): void {
    setWatch(section.watch)
    setApplied(section.applied)
  }

  return (
    <ProfilePart
      heading="Companies"
      part={part}
      onSave={() => {
        part.send(
          { watch, applied },
          { watch, applied: applied.map((job) => job.company) },
          show,
        )
      }}
    >
      <TextListEditor
        items={watch}
        onChange={(next) => {
          part.edit(() => setWatch(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a company to watch"
        itemNoun="company to watch"
        listLabel="Companies you watch"
        oneNoun="A company"
        pluralNoun="companies to watch"
        cap={MAX_WATCHED}
        maxLength={MAX_COMPANY_LENGTH}
      />
      <PairsEditor
        legend="Jobs you have applied to"
        listLabel="Your applications"
        items={applied}
        onChange={(next) => {
          part.edit(() => setApplied(next))
        }}
        onNotice={part.say}
        held={part.held}
        firstLabel="Company"
        itemNoun="job"
        second={{ kind: 'text', label: 'Job title' }}
        itemFrom={(company, typedTitle) => {
          const title = composed(typedTitle)
          // Refused here as the backend would refuse it, so no job is listed
          // without its title.
          if (title === '') {
            return { notice: `A job title cannot be blank: ${company}` }
          }
          if (lengthOf(company) > MAX_COMPANY_LENGTH) {
            return { notice: `A company can be at most ${MAX_COMPANY_LENGTH} characters: ${company}` }
          }
          if (lengthOf(title) > MAX_TITLE_LENGTH) {
            return { notice: `A job title can be at most ${MAX_TITLE_LENGTH} characters: ${title}` }
          }
          return { item: { company, title } }
        }}
        keyOf={sameJob}
        nameOf={jobShown}
        shownAs={jobShown}
        cap={MAX_APPLIED}
        pluralNoun="jobs applied to"
      />
    </ProfilePart>
  )
}
