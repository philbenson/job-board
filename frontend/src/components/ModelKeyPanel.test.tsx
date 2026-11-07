import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  ModelKeyRefusedBody,
  NoModelKeyBody,
  SavedModelKeyBody,
} from '../api/modelKey.ts'
import { Account } from './Account.tsx'
import { ModelKeyPanel } from './ModelKeyPanel.tsx'

// Clerk replaced by a stand-in, as in App.test.tsx, so no test reaches Clerk.
const clerk = vi.hoisted(() => ({
  signedIn: true,
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  ClerkLoading: () => null,
  ClerkFailed: () => null,
  Show: (props: { when: string; children: ReactNode }) =>
    (props.when === 'signed-in') === clerk.signedIn ? props.children : null,
  SignInButton: (props: { children: ReactNode }) => props.children,
  UserButton: () => <button type="button" aria-label="Open user menu" />,
  useAuth: () => ({
    isLoaded: true,
    isSignedIn: clerk.signedIn,
    getToken: clerk.getToken,
  }),
}))

const SESSION_TOKEN = 'header.payload.signature'
const KEY = 'sk-ant-api03-placeholder-wxyz'

const LOADING = 'Loading your model key…'
const NONE_SAVED = 'No key saved'
const CHECKING = 'Checking the key with Anthropic…'
const READ_FAILED = 'Could not load your model key'
const SAVE_FAILED = 'Could not save the key. Try again.'
const REMOVE_FAILED = 'Could not remove the key. Try again.'

const SAVED = {
  provider: 'anthropic',
  last_four: 'abcd',
  checked_at: '2026-11-07T12:00:00Z',
  usable: true,
} satisfies SavedModelKeyBody
const SAVED_LINE = 'Anthropic key ending in abcd, checked Nov 7, 2026'
const NEWLY_SAVED = {
  provider: 'anthropic',
  last_four: 'wxyz',
  checked_at: '2026-11-08T12:00:00Z',
  usable: true,
} satisfies SavedModelKeyBody
const NEWLY_SAVED_LINE = 'Anthropic key ending in wxyz, checked Nov 8, 2026'
const NONE = { detail: 'no model key saved' } satisfies NoModelKeyBody

type Reply = (init?: RequestInit) => Promise<Response>

// The panel's one route, answered per method as each test says; a method a
// test does not answer never answers.
function service(replies: { get?: Reply; put?: Reply; delete?: Reply }) {
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toLowerCase() as keyof typeof replies
    const reply = replies[method]
    return reply === undefined ? new Promise<Response>(() => {}) : reply(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

// A body the contract allows, typed so it changes when the backend's does.
function answer(
  status: number,
  body: SavedModelKeyBody | NoModelKeyBody | ModelKeyRefusedBody,
): Promise<Response> {
  return answerText(status, JSON.stringify(body))
}

function answerText(status: number, text: string): Promise<Response> {
  return Promise.resolve(
    new Response(text, {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function noContent(): Promise<Response> {
  return Promise.resolve(new Response(null, { status: 204 }))
}

function keyInput(): HTMLInputElement {
  return screen.getByLabelText<HTMLInputElement>('Anthropic API key')
}

function callsWith(fetchMock: ReturnType<typeof service>, method: string) {
  return fetchMock.mock.calls.filter(
    ([, init]) => (init?.method ?? 'GET') === method,
  )
}

describe('ModelKeyPanel', () => {
  beforeEach(() => {
    clerk.signedIn = true
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('shows it is loading, then that no key is saved, with the form to save one', async () => {
    const fetchMock = service({ get: () => answer(404, NONE) })

    render(<ModelKeyPanel />)

    expect(screen.getByText(LOADING)).toBeInTheDocument()
    expect(await screen.findByText(NONE_SAVED)).toBeInTheDocument()
    expect(keyInput()).toHaveAttribute('type', 'password')
    expect(keyInput()).toHaveAttribute('autocomplete', 'off')
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    const [, init] = fetchMock.mock.calls[0]
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${SESSION_TOKEN}`,
    )
  })

  it('shows a saved key by its last four and check date, with Replace and Remove', async () => {
    service({ get: () => answer(200, SAVED) })

    render(<ModelKeyPanel />)

    expect(await screen.findByText(SAVED_LINE)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Anthropic API key')).not.toBeInTheDocument()
  })

  it('asks for a key saved under an old encryption key to be entered again, with the form open', async () => {
    service({ get: () => answer(200, { ...SAVED, usable: false }) })

    render(<ModelKeyPanel />)

    expect(
      await screen.findByText(
        'Your saved key ending in abcd can no longer be used. Enter it again.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(SAVED_LINE)).not.toBeInTheDocument()
    expect(keyInput()).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Replace' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it.each([
    ['the service fails', () => answerText(500, '{"detail": "down"}')],
    ['the request fails', () => Promise.reject(new TypeError('Failed to fetch'))],
  ])('says the key could not be loaded when %s', async (_case, reply) => {
    service({ get: reply })

    render(<ModelKeyPanel />)

    expect(await screen.findByText(READ_FAILED)).toBeInTheDocument()
    expect(screen.queryByText(NONE_SAVED)).not.toBeInTheDocument()
  })

  it('says the key could not be loaded when Clerk has no session token', async () => {
    clerk.getToken.mockResolvedValue(null)
    const fetchMock = service({ get: () => answer(404, NONE) })

    render(<ModelKeyPanel />)

    expect(await screen.findByText(READ_FAILED)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('checks a key, then shows it saved, clears the input and keeps nothing in the browser', async () => {
    let reply: (response: Response) => void = () => {}
    const fetchMock = service({
      get: () => answer(404, NONE),
      put: () =>
        new Promise<Response>((resolve) => {
          reply = resolve
        }),
    })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)
    await user.type(await screen.findByLabelText('Anthropic API key'), KEY)

    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(screen.getByText(CHECKING)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    const [[, init]] = callsWith(fetchMock, 'PUT')
    expect(JSON.parse(String(init?.body))).toEqual({
      provider: 'anthropic',
      key: KEY,
    })
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      `Bearer ${SESSION_TOKEN}`,
    )

    await act(async () => {
      reply(new Response(JSON.stringify(NEWLY_SAVED), { status: 200 }))
    })

    expect(await screen.findByText(NEWLY_SAVED_LINE)).toBeInTheDocument()
    expect(screen.queryByText(CHECKING)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replace' }))
    expect(keyInput()).toHaveValue('')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it.each([
    [422, 'malformed', 'That does not look like an Anthropic API key.'],
    [422, 'rejected', 'Anthropic did not accept that key.'],
    [422, 'not-permitted', 'That key cannot use the model this app runs.'],
    [
      503,
      'unavailable',
      "Anthropic did not confirm the key, so nothing was saved. Try again later; if it keeps happening, check the key's limits in the Claude Console.",
    ],
    [
      429,
      'check-running',
      'A check of your key is already running. Wait for it to finish.',
    ],
    [
      429,
      'too-many-checks',
      'You have checked too many keys in the last hour. Try again later.',
    ],
  ] as const)(
    'shows the backend sentence for a %i %s refusal',
    async (status, reason, detail) => {
      service({
        get: () => answer(404, NONE),
        put: () => answer(status, { detail, reason }),
      })
      const user = userEvent.setup()
      render(<ModelKeyPanel />)
      await user.type(await screen.findByLabelText('Anthropic API key'), KEY)

      await user.click(screen.getByRole('button', { name: 'Save' }))

      expect(await screen.findByText(detail)).toBeInTheDocument()
      expect(screen.getByText(NONE_SAVED)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    },
  )

  it.each([
    ['the service fails', () => answerText(500, '{"detail": "down"}')],
    ['the request fails', () => Promise.reject(new TypeError('Failed to fetch'))],
  ])('says the key could not be saved when %s', async (_case, reply) => {
    service({ get: () => answer(404, NONE), put: reply })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)
    await user.type(await screen.findByLabelText('Anthropic API key'), KEY)

    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText(SAVE_FAILED)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('gives up on a save after thirty seconds without an answer', async () => {
    vi.useFakeTimers()
    service({ get: () => answer(404, NONE) })
    render(<ModelKeyPanel />)
    await act(() => vi.advanceTimersByTimeAsync(0))
    fireEvent.change(keyInput(), { target: { value: KEY } })

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await act(() => vi.advanceTimersByTimeAsync(29_999))
    expect(screen.getByText(CHECKING)).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(1))

    expect(screen.getByText(SAVE_FAILED)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('removes the key without asking, then offers the form again', async () => {
    const fetchMock = service({
      get: () => answer(200, SAVED),
      delete: noContent,
    })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)

    await user.click(await screen.findByRole('button', { name: 'Remove' }))

    expect(await screen.findByText(NONE_SAVED)).toBeInTheDocument()
    expect(screen.queryByText(SAVED_LINE)).not.toBeInTheDocument()
    expect(keyInput()).toHaveValue('')
    expect(callsWith(fetchMock, 'DELETE')).toHaveLength(1)
  })

  it('clears a key being typed when the saved one is removed', async () => {
    service({ get: () => answer(200, SAVED), delete: noContent })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)
    await user.click(await screen.findByRole('button', { name: 'Replace' }))
    await user.type(keyInput(), KEY)

    await user.click(screen.getByRole('button', { name: 'Remove' }))

    expect(await screen.findByText(NONE_SAVED)).toBeInTheDocument()
    expect(keyInput()).toHaveValue('')
  })

  it('says the key could not be removed when the service fails, and keeps showing it', async () => {
    service({
      get: () => answer(200, SAVED),
      delete: () => answerText(500, '{"detail": "down"}'),
    })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)

    await user.click(await screen.findByRole('button', { name: 'Remove' }))

    expect(await screen.findByText(REMOVE_FAILED)).toBeInTheDocument()
    expect(screen.getByText(SAVED_LINE)).toBeInTheDocument()
  })

  it('reaches the input and Save by Tab when no key is saved', async () => {
    service({ get: () => answer(404, NONE) })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)
    await screen.findByText(NONE_SAVED)

    await user.tab()
    expect(keyInput()).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus()
  })

  it('reaches Replace and Remove by Tab when a key is saved', async () => {
    service({ get: () => answer(200, SAVED) })
    const user = userEvent.setup()
    render(<ModelKeyPanel />)
    await screen.findByText(SAVED_LINE)

    await user.tab()
    expect(screen.getByRole('button', { name: 'Replace' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveFocus()
  })
})

describe('Account', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the model key panel to a signed-in person only', () => {
    service({})
    clerk.signedIn = true
    const { unmount } = render(<Account />)
    expect(screen.getByRole('region', { name: 'Model key' })).toBeInTheDocument()
    unmount()

    clerk.signedIn = false
    render(<Account />)
    expect(screen.queryByRole('region', { name: 'Model key' })).not.toBeInTheDocument()
  })
})
