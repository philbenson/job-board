import { useState } from 'react'
import { COMPANY_SIZE_NAMES, type CompanySize, type StoredSection } from '../api/profile.ts'
import { ChoiceSet } from './ChoiceSet.tsx'
import { SIZE_CHOICES } from './profileChoices.ts'
import { YesNoField } from './ProfileFields.tsx'
import { MAX_INDUSTRIES, MAX_INDUSTRY_LENGTH } from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

type DealBreakers = StoredSection<'/profile/deal-breakers'>

const NO_AGENCIES = 'No recruiting agencies'

/** Industries and company sizes ruled out, and whether agencies are. */
export function DealBreakersPart({ stored }: { stored: DealBreakers | null }) {
  const part = useProfilePart(
    '/profile/deal-breakers',
    stored,
    'Could not save your deal-breakers; your changes are still here',
  )
  const [industries, setIndustries] = useState(stored?.industries ?? [])
  const [sizes, setSizes] = useState<CompanySize[]>(stored?.company_sizes ?? [])
  const [noAgencies, setNoAgencies] = useState(stored?.no_agencies ?? false)

  function show(section: DealBreakers): void {
    setIndustries(section.industries)
    setSizes(section.company_sizes)
    setNoAgencies(section.no_agencies)
  }

  return (
    <ProfilePart
      heading="Deal-breakers"
      part={part}
      onSave={() => {
        part.send(
          { industries, company_sizes: sizes, no_agencies: noAgencies },
          {
            industries,
            company_sizes: sizes.map((size) => COMPANY_SIZE_NAMES[size]),
            no_agencies: NO_AGENCIES,
          },
          show,
        )
      }}
    >
      <TextListEditor
        items={industries}
        onChange={(next) => {
          part.edit(() => setIndustries(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add an industry you will not work in"
        listLabel="Industries you will not work in"
        oneNoun="An industry"
        pluralNoun="industries"
        cap={MAX_INDUSTRIES}
        maxLength={MAX_INDUSTRY_LENGTH}
      />
      <ChoiceSet
        legend="Company sizes you will not work for"
        choices={SIZE_CHOICES}
        selected={sizes}
        onChange={(next) => {
          part.edit(() => setSizes(next))
        }}
        held={part.held}
      />
      <YesNoField
        label={NO_AGENCIES}
        checked={noAgencies}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setNoAgencies(next))
        }}
      />
    </ProfilePart>
  )
}
