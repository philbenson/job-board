import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { MAX_GAP_LENGTH, MAX_GAPS } from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { SECTION_HEADINGS } from './sectionHeadings.ts'
import { TextListEditor } from './TextListEditor.tsx'
import { useProfilePart } from './useProfilePart.ts'

type Gaps = StoredSection<'/profile/gaps'>

/** What the person lacks but would apply anyway, and what they would give up. */
export function GapsPart({ stored, version }: { stored: Gaps | null; version: number }) {
  const [applyWith, setApplyWith] = useState(stored?.apply_with ?? [])
  const [tradeOffs, setTradeOffs] = useState(stored?.trade_offs ?? [])
  const part = useProfilePart(
    '/profile/gaps',
    stored,
    'Could not save your gaps and trade-offs; your changes are still here',
    version,
    show,
  )

  function show(section: Gaps): void {
    setApplyWith(section.apply_with)
    setTradeOffs(section.trade_offs)
  }

  return (
    <ProfilePart
      heading={SECTION_HEADINGS.gaps}
      part={part}
      onSave={() => {
        const body = { apply_with: applyWith, trade_offs: tradeOffs }
        part.send(body, body)
      }}
    >
      <TextListEditor
        items={applyWith}
        onChange={(next) => {
          part.edit(() => setApplyWith(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a gap you would apply with"
        itemNoun="gap you would apply with"
        listLabel="Gaps you would apply with"
        oneNoun="A gap"
        pluralNoun="gaps"
        cap={MAX_GAPS}
        maxLength={MAX_GAP_LENGTH}
      />
      <TextListEditor
        items={tradeOffs}
        onChange={(next) => {
          part.edit(() => setTradeOffs(next))
        }}
        onNotice={part.say}
        held={part.held}
        inputLabel="Add a trade-off you would make"
        itemNoun="trade-off you would make"
        listLabel="Trade-offs you would make"
        oneNoun="A trade-off"
        pluralNoun="trade-offs"
        cap={MAX_GAPS}
        maxLength={MAX_GAP_LENGTH}
      />
    </ProfilePart>
  )
}
