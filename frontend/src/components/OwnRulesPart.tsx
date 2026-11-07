import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { MAX_RULE_LENGTH, MAX_RULES } from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

/** Rules of the person's own, in their words, for each posting. */
export function OwnRulesPart({ stored }: { stored: StoredSection<'/profile/own-rules'> | null }) {
  const part = useProfilePart(
    '/profile/own-rules',
    stored,
    'Could not save your own rules; your changes are still here',
  )
  const [rules, setRules] = useState(stored?.rules ?? [])

  return (
    <ProfilePart
      heading="Your own rules"
      part={part}
      onSave={() => {
        part.send({ rules }, { rules }, (section) => {
          setRules(section.rules)
        })
      }}
    >
      <TextListEditor
        items={rules}
        onChange={(next) => {
          part.edit(() => setRules(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a rule"
        listLabel="Your rules"
        oneNoun="A rule"
        pluralNoun="rules"
        cap={MAX_RULES}
        maxLength={MAX_RULE_LENGTH}
      />
    </ProfilePart>
  )
}
