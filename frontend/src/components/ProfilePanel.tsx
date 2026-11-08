import { useAuth } from '@clerk/react'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
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
import { EXCHANGE_TIMEOUT_MS, type ProfileReads } from './useProfilePart.ts'

type Loading =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'loaded'; profile: ProfileBody }

const NOT_REFRESHED = "Could not load the interviewer's latest saves. Reload the page to see them."

/**
 * The signed-in person's profile: loads it once on mount, then shows each
 * section as its own part, with its own editors and its own Save. Parts save
 * apart, so one part's save never holds or changes another.
 *
 * `saves` counts the interviewer's saves the page has heard of: each new
 * count reads the profile again, a newer read aborting an older, and hands
 * every part its section as now stored with the read's number, counted when
 * it was sent, for the part to take or, while it holds unsaved edits or a
 * save, or when the read was sent before its last save answered, to leave.
 */
export function ProfilePanel({ saves = 0 }: { saves?: number }) {
  const { getToken } = useAuth()
  const [loading, setLoading] = useState<Loading>({ kind: 'loading' })
  // Numbers each read after the first as it is sent, the first load being 0.
  const sent = useRef(0)
  // The number of the newest read that answered; a newer read aborts an
  // older, so it only grows.
  const [version, setVersion] = useState(0)
  const newestSent = useCallback(() => sent.current, [])
  const reads: ProfileReads = useMemo(() => ({ version, newestSent }), [version, newestSent])
  // Whether the newest read after the first failed.
  const [missed, setMissed] = useState(false)
  const headingId = useId()
  // The read in flight, first or later; a newer one aborts it.
  const reading = useRef<AbortController | null>(null)
  const seenSaves = useRef(saves)

  useEffect(() => {
    const controller = new AbortController()
    reading.current = controller
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
      reading.current?.abort()
    }
  }, [getToken])

  useEffect(() => {
    if (saves === seenSaves.current) {
      return
    }
    seenSaves.current = saves
    sent.current += 1
    const number = sent.current
    reading.current?.abort()
    const controller = new AbortController()
    reading.current = controller
    void withToken(
      getToken,
      EXCHANGE_TIMEOUT_MS,
      controller.signal,
      fetchProfile,
      'unavailable',
    ).then((read: ProfileRead) => {
      if (read === 'aborted') {
        return
      }
      if (read === 'unavailable') {
        // A first load this read replaced has failed with it.
        setLoading((was) => (was.kind === 'loading' ? { kind: 'unavailable' } : was))
        setMissed(true)
        return
      }
      setMissed(false)
      setLoading(read)
      setVersion(number)
    })
  }, [saves, getToken])

  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId}>Your profile</h2>
      {/* Stays on the page, changing its words, which a screen reader announces. */}
      <p role="status">
        {loading.kind === 'loading'
          ? 'Loading your profile…'
          : loading.kind === 'loaded' && missed
            ? NOT_REFRESHED
            : ''}
      </p>
      {loading.kind === 'unavailable' && <p role="alert">Could not load your profile. Reload the page to try again.</p>}
      {loading.kind === 'loaded' && (
        <>
          <p>Scoring reads every section except pace, which nothing reads yet.</p>
          <TargetTitlesPart stored={loading.profile.target_titles} reads={reads} />
          <NearbyTitlesPart stored={loading.profile.title_range} reads={reads} />
          <PlacesPart stored={loading.profile.places} reads={reads} />
          <PayPart stored={loading.profile.pay} reads={reads} />
          <SkillsPart stored={loading.profile.skills} reads={reads} />
          <GapsPart stored={loading.profile.gaps} reads={reads} />
          <DealBreakersPart stored={loading.profile.deal_breakers} reads={reads} />
          <CompaniesPart stored={loading.profile.companies} reads={reads} />
          <PacePart stored={loading.profile.pace} reads={reads} />
          <OwnRulesPart stored={loading.profile.own_rules} reads={reads} />
        </>
      )}
    </section>
  )
}
