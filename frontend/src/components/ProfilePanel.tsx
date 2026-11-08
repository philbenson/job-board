import { useAuth } from '@clerk/react'
import { useEffect, useId, useState } from 'react'
import { fetchProfile, type ProfileBody, type ProfileRead } from '../api/profile.ts'
import { withToken } from '../api/withToken.ts'
import { CompaniesPart } from './CompaniesPart.tsx'
import { DealBreakersPart } from './DealBreakersPart.tsx'
import { GapsPart } from './GapsPart.tsx'
import { NearbyTitlesPart } from './NearbyTitlesPart.tsx'
import { OwnRulesPart } from './OwnRulesPart.tsx'
import { PacePart } from './PacePart.tsx'
import { PayPart } from './PayPart.tsx'
import { PlacesPart } from './PlacesPart.tsx'
import { SkillsPart } from './SkillsPart.tsx'
import { TargetTitlesPart } from './TargetTitlesPart.tsx'
import { EXCHANGE_TIMEOUT_MS } from './useProfilePart.ts'

type Loading =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'loaded'; profile: ProfileBody }

/**
 * The signed-in person's profile: loads it once on mount, then shows each
 * section as its own part, with its own editors and its own Save. Parts save
 * apart, so one part's save never holds or changes another.
 */
export function ProfilePanel() {
  const { getToken } = useAuth()
  const [loading, setLoading] = useState<Loading>({ kind: 'loading' })
  const headingId = useId()

  useEffect(() => {
    const controller = new AbortController()
    // No token to give is no answer either.
    void withToken(
      getToken,
      EXCHANGE_TIMEOUT_MS,
      controller.signal,
      fetchProfile,
      'unavailable',
    ).then((read: ProfileRead) => {
      // An aborted load belongs to an effect that has been cleaned up; see
      // ServiceStatus for why its answer must not be shown.
      if (read === 'aborted') {
        return
      }
      setLoading(read === 'unavailable' ? { kind: 'unavailable' } : read)
    })
    return () => {
      controller.abort()
    }
  }, [getToken])

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>Your profile</h2>
      {loading.kind === 'loading' && <p role="status">Loading your profile…</p>}
      {loading.kind === 'unavailable' && <p role="alert">Could not load your profile. Reload the page to try again.</p>}
      {loading.kind === 'loaded' && (
        <>
          <p>Scoring reads every section except pace, which nothing reads yet.</p>
          <TargetTitlesPart stored={loading.profile.target_titles} />
          <NearbyTitlesPart stored={loading.profile.title_range} />
          <PlacesPart stored={loading.profile.places} />
          <PayPart stored={loading.profile.pay} />
          <SkillsPart stored={loading.profile.skills} />
          <GapsPart stored={loading.profile.gaps} />
          <DealBreakersPart stored={loading.profile.deal_breakers} />
          <CompaniesPart stored={loading.profile.companies} />
          <PacePart stored={loading.profile.pace} />
          <OwnRulesPart stored={loading.profile.own_rules} />
        </>
      )}
    </section>
  )
}
