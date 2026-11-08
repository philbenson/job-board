import { useState } from 'react'
import type { StoredSection } from '../api/profile.ts'
import { PairsEditor } from './PairsEditor.tsx'
import { MAX_SKILL_LENGTH, MAX_SKILLS } from './profileLimits.ts'
import { ProfilePart } from './ProfilePart.tsx'
import { lengthOf, repeatKey, wholeNumberFrom } from './profileText.ts'
import { SECTION_HEADINGS } from './sectionHeadings.ts'
import { useProfilePart } from './useProfilePart.ts'

type Skill = StoredSection<'/profile/skills'>['skills'][number]

// The backend stores under a year as 0 years.
function skillShown({ name, years }: Skill): string {
  const often = years === 0 ? 'under a year' : `${years} ${years === 1 ? 'year' : 'years'}`
  return `${name}, ${often}`
}

/** Each skill the person has, with the whole years they have used it. */
export function SkillsPart({ stored }: { stored: StoredSection<'/profile/skills'> | null }) {
  const part = useProfilePart(
    '/profile/skills',
    stored,
    'Could not save your skills; your changes are still here',
  )
  const [skills, setSkills] = useState(stored?.skills ?? [])

  return (
    <ProfilePart
      heading={SECTION_HEADINGS.skills}
      part={part}
      onSave={() => {
        part.send({ skills }, { skills: skills.map((skill) => skill.name) }, (section) => {
          setSkills(section.skills)
        })
      }}
    >
      <PairsEditor
        legend="Your skills and years with each"
        listLabel="Your skills"
        items={skills}
        onChange={(next) => {
          part.edit(() => setSkills(next))
        }}
        onNotice={part.say}
        held={part.held}
        firstLabel="Skill"
        itemNoun="skill"
        second={{ kind: 'number', label: 'Years' }}
        itemFrom={(name, typedYears) => {
          if (lengthOf(name) > MAX_SKILL_LENGTH) {
            return { notice: `A skill can be at most ${MAX_SKILL_LENGTH} characters: ${name}` }
          }
          const years = wholeNumberFrom(typedYears)
          if (years === 'not whole') {
            return { notice: 'Enter years as a whole number' }
          }
          if (years === 'too large') {
            return { notice: 'The years are too large' }
          }
          return { item: { name, years } }
        }}
        keyOf={(skill) => repeatKey(skill.name)}
        nameOf={(skill) => skill.name}
        shownAs={skillShown}
        cap={MAX_SKILLS}
        pluralNoun="skills"
      />
    </ProfilePart>
  )
}
