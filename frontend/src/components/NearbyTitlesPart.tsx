import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { YesNoField } from './ProfileFields.tsx'
import { MAX_NEARBY_TITLES, MAX_TITLE_LENGTH } from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

type TitleRange = StoredSection<'/profile/title-range'>

const LOWER_LEVEL = 'A lower level than my target titles is fine'

/** Titles close to the target titles, and whether one level down is fine. */
export function NearbyTitlesPart({ stored }: { stored: TitleRange | null }) {
  const part = useProfilePart(
    '/profile/title-range',
    stored,
    'Could not save your nearby titles; your changes are still here',
  )
  const [titles, setTitles] = useState(stored?.nearby_titles ?? [])
  const [lowerOk, setLowerOk] = useState(stored?.lower_level_ok ?? false)

  function show(section: TitleRange): void {
    setTitles(section.nearby_titles)
    setLowerOk(section.lower_level_ok)
  }

  return (
    <ProfilePart
      heading="Nearby titles"
      part={part}
      onSave={() => {
        part.send(
          { nearby_titles: titles, lower_level_ok: lowerOk },
          { nearby_titles: titles, lower_level_ok: LOWER_LEVEL },
          show,
        )
      }}
    >
      <TextListEditor
        items={titles}
        onChange={(next) => {
          part.edit(() => setTitles(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a nearby title"
        listLabel="Your nearby titles"
        oneNoun="A nearby title"
        pluralNoun="nearby titles"
        cap={MAX_NEARBY_TITLES}
        maxLength={MAX_TITLE_LENGTH}
      />
      <YesNoField
        label={LOWER_LEVEL}
        checked={lowerOk}
        held={part.held}
        onChange={(next) => {
          part.edit(() => setLowerOk(next))
        }}
      />
    </ProfilePart>
  )
}
