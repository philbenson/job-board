import type { FailureCode } from '../api/interview.ts'

/**
 * What the alert line says when the interviewer's last turn failed, by the
 * code the backend gives. Keyed by the generated union, so a code the backend
 * adds fails the type check until it has its sentence. Try again is offered
 * for each: where the key is the problem, the retry's own refusal says so.
 */
export const FAILURE_SENTENCES: Record<FailureCode, string> = {
  'timed-out': 'Anthropic took too long to answer.',
  'connection-error': 'Could not reach Anthropic.',
  rejected: 'Anthropic did not accept your key. Save a working key above.',
  'not-permitted': 'Your key is not allowed to use this model.',
  'model-not-found': 'Anthropic no longer offers the model the interviewer uses.',
  'no-credit': 'Your Anthropic account is out of credit.',
  'rate-limited': 'Anthropic is limiting requests on your key. Wait a minute.',
  'server-error': 'Anthropic had a problem on its side.',
  refused: 'Anthropic refused the request.',
  'cut-off': "The interviewer's reply ran past its length limit.",
  'empty-reply': 'The interviewer sent an empty reply.',
  declined: 'The interviewer declined to reply.',
  'not-sealed-here': 'Your key was saved under another setup of this service. Save it again above.',
  unopenable: 'Your saved key could not be opened. Save it again above.',
  interrupted: 'The service restarted while the interviewer was taking its turn.',
  unexpected: "Something went wrong on the service's side.",
}
