import { useState } from 'react'
import { MAX_TARGET_TITLES, MAX_TITLE_LENGTH } from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

/** The job titles the person is looking for, which scoring reads. */
export function TargetTitlesPart({ stored }: { stored: string[] }) {
  const part = useProfilePart(
    '/profile/target-titles',
    stored,
    'Could not save your target titles; your changes are still here',
  )
  const [titles, setTitles] = useState(stored)

  return (
    <ProfilePart
      heading="Target titles"
      part={part}
      onSave={() => {
        part.send({ titles }, { titles }, setTitles)
      }}
    >
      <TextListEditor
        items={titles}
        onChange={(next) => {
          part.edit(() => setTitles(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a target title"
        listLabel="Your target titles"
        oneNoun="A target title"
        pluralNoun="target titles"
        cap={MAX_TARGET_TITLES}
        maxLength={MAX_TITLE_LENGTH}
        emptyText="No target titles yet"
      />
    </ProfilePart>
  )
}
