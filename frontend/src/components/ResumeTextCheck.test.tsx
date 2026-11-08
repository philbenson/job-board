import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { StorageRefusalBody } from '../api/resume.ts'
import type { ResumeTextBody, TextRefusalBody } from '../api/resumeText.ts'
import { ResumeTextCheck } from './ResumeTextCheck.tsx'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const SESSION_TOKEN = 'header.payload.signature'

const FOUND_LINE =
  'Here is the text read from your resume. Check it, put anything out of order back in order, and save it.'
const CUT_LINE =
  'Your resume is longer than 15,000 characters or 50 pages, so only its start is here. Check it and save.'
const NONE_FOUND_LINE =
  'No text could be read from your resume; it may be a scanned image. Type or paste its text here and save it.'
const FAILED_LINE = "Your resume's text could not be read. Type or paste its text here and save it."
const NO_STATE_LINE =
  'This resume was uploaded before its text was read. Upload it again to read its text, or type or paste it here and save it.'
const SAVING = "Saving your resume's text…"
const SAVED = 'Saved.'
const REPLACED_LINE =
  'Your resume was replaced since this text was read. Reload the page to check the new text.'
const NOT_LOADED = "Could not load your resume's text"
const NOT_SAVED = "Could not save your resume's text"
const NOT_SET_UP = 'Resume storage is not set up on this service yet'
const STORAGE_DOWN = 'Could not reach resume storage; try again later'

// Microseconds the browser's Date cannot hold, which must go back as they came.
const UPLOADED_AT = '2026-11-07T20:29:59.747970Z'
const CHECKED_AT = '2026-11-07T21:00:00.123456Z'
const TEXT = 'Avery Example\nStaff Engineer, Example Widgets\n\nLed the move to small services.'
const CORRECTED = 'Avery Example\navery@example.com, 555-0142\n\nLed the move to small services.'

// The page's own way of writing a time, so the tests hold in any locale and
// time zone they run in.
function shownTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

function read(overrides: Partial<ResumeTextBody> = {}): ResumeTextBody {
  return { uploaded_at: UPLOADED_AT, state: 'found', text: TEXT, checked_at: null, ...overrides }
}

// A body the contract allows, typed so it changes when the backend's does.
function answer(
  status: number,
  body: ResumeTextBody | StorageRefusalBody | TextRefusalBody,
): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

// A request that never answers, and fails the way fetch does when aborted.
function answerOnlyAbort(init?: RequestInit): Promise<Response> {
  return new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => {
      reject(new DOMException('The request was aborted', 'AbortError'))
    })
  })
}

type Reply = (init?: RequestInit) => Promise<Response>

// The text route answers a read with `reading` and a save with `save`; until a
// test says, a save never answers.
function service(reading: Reply, save: Reply = answerOnlyAbort) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url !== '/api/resume/text') {
      return Promise.reject(new TypeError(`unexpected request to ${url}`))
    }
    return init?.method === 'PUT' ? save(init) : reading(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function puts(fetchMock: ReturnType<typeof service>): RequestInit[] {
  return fetchMock.mock.calls
    .map(([, init]) => init)
    .filter((init): init is RequestInit => init?.method === 'PUT')
}

function check(): HTMLElement {
  return screen.getByRole('region', { name: 'Resume text' })
}

function box(): HTMLTextAreaElement {
  return screen.getByLabelText<HTMLTextAreaElement>("Your resume's text")
}

function save(): HTMLElement {
  return screen.getByRole('button', { name: 'Save' })
}

function status(): HTMLElement {
  return within(check()).getByRole('status')
}

function alertLine(): HTMLElement {
  return within(check()).getByRole('alert')
}

describe('ResumeTextCheck', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('mounts its status and alert lines empty, then reads the text with the token', async () => {
    let answerRead: (response: Response) => void = () => {}
    const fetchMock = service(
      () =>
        new Promise<Response>((resolve) => {
          answerRead = resolve
        }),
    )

    render(<ResumeTextCheck />)

    expect(status()).toHaveTextContent(/^$/)
    expect(alertLine()).toHaveTextContent(/^$/)
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalled()
    })
    await act(async () => {
      answerRead(new Response(JSON.stringify(read()), { status: 200 }))
      await Promise.resolve()
    })
    expect(await within(check()).findByText(FOUND_LINE)).toBe(status())
    expect(alertLine()).toHaveTextContent(/^$/)
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/resume/text')
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)
  })

  it.each([
    ['found', TEXT, FOUND_LINE],
    ['cut', TEXT, CUT_LINE],
    ['none_found', null, NONE_FOUND_LINE],
    ['failed', null, FAILED_LINE],
    [null, null, NO_STATE_LINE],
  ] as const)('says what reading gave for the state %s', async (state, text, line) => {
    service(() => answer(200, read({ state, text })))

    render(<ResumeTextCheck />)

    expect(await within(check()).findByText(line)).toBe(status())
    expect(box()).toHaveValue(text ?? '')
    expect(screen.queryByText(/^You checked this text on/)).not.toBeInTheDocument()
  })

  it('says when the person checked the text', async () => {
    service(() => answer(200, read({ checked_at: CHECKED_AT })))

    render(<ResumeTextCheck />)

    expect(
      await screen.findByText(`You checked this text on ${shownTime(CHECKED_AT)}.`),
    ).toBeInTheDocument()
  })

  // Once saved, the text is the person's, so what reading the file gave no
  // longer says anything about it.
  it.each([
    ['found', TEXT],
    ['cut', TEXT],
    ['none_found', 'Typed by the person'],
    ['failed', 'Typed by the person'],
    [null, 'Typed by the person'],
  ] as const)('shows no reading line for the state %s once the text was checked', async (state, text) => {
    service(() => answer(200, read({ state, text, checked_at: CHECKED_AT })))

    render(<ResumeTextCheck />)

    expect(
      await screen.findByText(`You checked this text on ${shownTime(CHECKED_AT)}.`),
    ).toBeInTheDocument()
    expect(box()).toHaveValue(text)
    expect(status()).toHaveTextContent(/^$/)
  })

  it('shows markup in the text as the box holds it, never as markup', async () => {
    const markup = `${TEXT}\n<b>Lead</b> <img src="x" onerror="alert(1)"> &amp;`
    service(() => answer(200, read({ text: markup })))

    render(<ResumeTextCheck />)

    await within(check()).findByText(FOUND_LINE)
    expect(box()).toHaveValue(markup)
    expect(check().querySelector('b, img')).toBeNull()
  })

  it('counts characters as people do, tied to the box, and holds Save past the cap', async () => {
    const fetchMock = service(() => answer(200, read({ text: 'Avery 😀' })))
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)

    expect(box()).toHaveAccessibleDescription('7 of 15,000 characters')
    const count = screen.getByText('7 of 15,000 characters')
    expect(count).not.toHaveAttribute('role')
    expect(count).not.toHaveAttribute('aria-live')
    expect(save()).toHaveAttribute('aria-disabled', 'false')

    fireEvent.change(box(), { target: { value: '😀'.repeat(15_000) } })
    expect(box()).toHaveAccessibleDescription('15,000 of 15,000 characters')
    expect(save()).toHaveAttribute('aria-disabled', 'false')

    fireEvent.change(box(), { target: { value: `${'😀'.repeat(15_000)}x` } })
    expect(box()).toHaveAccessibleDescription('15,001 of 15,000 characters')
    expect(save()).toHaveAttribute('aria-disabled', 'true')
    await user.click(save())
    expect(puts(fetchMock)).toEqual([])
  })

  it('saves the typed text with the upload time exactly as read, holding Save with focus on it', async () => {
    let answerSave: (response: Response) => void = () => {}
    const fetchMock = service(
      () => answer(200, read()),
      () =>
        new Promise<Response>((resolve) => {
          answerSave = resolve
        }),
    )
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)

    fireEvent.change(box(), { target: { value: `  ${CORRECTED}  ` } })
    save().focus()
    await user.keyboard('{Enter}')

    expect(status()).toHaveTextContent(SAVING)
    expect(save()).toHaveAttribute('aria-disabled', 'true')
    expect(save()).toHaveFocus()
    await user.click(save())
    expect(puts(fetchMock)).toHaveLength(1)
    const [init] = puts(fetchMock)
    expect(JSON.parse(String(init?.body))).toEqual({
      text: `  ${CORRECTED}  `,
      uploaded_at: UPLOADED_AT,
    })
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)

    await act(async () => {
      answerSave(
        new Response(JSON.stringify(read({ text: CORRECTED, checked_at: CHECKED_AT })), {
          status: 200,
        }),
      )
      await Promise.resolve()
    })

    expect(await within(check()).findByText(SAVED)).toBe(status())
    expect(screen.getByText(`You checked this text on ${shownTime(CHECKED_AT)}.`)).toBeInTheDocument()
    // What the backend kept, which it cleaned.
    expect(box()).toHaveValue(CORRECTED)
    expect(save()).toHaveAttribute('aria-disabled', 'false')
    expect(save()).toHaveFocus()
    expect(alertLine()).toHaveTextContent(/^$/)
  })

  it('holds the box while a save is out, keeping focus in it, then shows what was saved', async () => {
    let answerSave: (response: Response) => void = () => {}
    service(
      () => answer(200, read()),
      () =>
        new Promise<Response>((resolve) => {
          answerSave = resolve
        }),
    )
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)
    fireEvent.change(box(), { target: { value: CORRECTED } })
    await user.click(save())
    expect(status()).toHaveTextContent(SAVING)

    await user.type(box(), ' and a second one')
    expect(box()).toHaveValue(CORRECTED)
    expect(box()).toHaveFocus()
    expect(box()).toHaveAttribute('readonly')
    expect(box()).toHaveAttribute('aria-disabled', 'true')
    // A change that gets past the hold, as a script's might, is ignored too.
    fireEvent.change(box(), { target: { value: 'pasted during the save' } })
    expect(box()).toHaveValue(CORRECTED)

    await act(async () => {
      answerSave(
        new Response(JSON.stringify(read({ text: CORRECTED, checked_at: CHECKED_AT })), {
          status: 200,
        }),
      )
      await Promise.resolve()
    })

    expect(await within(check()).findByText(SAVED)).toBe(status())
    expect(box()).toHaveValue(CORRECTED)
    expect(box()).not.toHaveAttribute('readonly')
    expect(box()).toHaveAttribute('aria-disabled', 'false')
    expect(box()).toHaveFocus()
  })

  it('stops saying saved once the text changes again', async () => {
    service(
      () => answer(200, read()),
      () => answer(200, read({ checked_at: CHECKED_AT })),
    )
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)
    await user.click(save())
    await within(check()).findByText(SAVED)

    await user.type(box(), '!')

    expect(status()).toHaveTextContent(/^$/)
  })

  it('says the resume was replaced for a 409, keeping the typed text', async () => {
    service(
      () => answer(200, read()),
      () => answer(409, { detail: 'Your resume was replaced since this text was read' }),
    )
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)

    fireEvent.change(box(), { target: { value: CORRECTED } })
    await user.click(save())

    expect(await within(check()).findByText(REPLACED_LINE)).toBe(alertLine())
    expect(box()).toHaveValue(CORRECTED)
    expect(status()).toHaveTextContent(/^$/)
    expect(save()).toHaveAttribute('aria-disabled', 'false')
  })

  it("shows the backend's message for a 422", async () => {
    const message = 'The resume text cannot contain control characters other than line breaks and tabs'
    service(
      () => answer(200, read()),
      () =>
        answer(422, {
          detail: [{ type: 'resume_text_control_character', loc: ['body', 'text'], msg: message }],
        }),
    )
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)

    await user.click(save())

    expect(await within(check()).findByText(message)).toBe(alertLine())
    expect(box()).toHaveValue(TEXT)
  })

  it.each([
    ['storage is not set up', () => answer(503, { detail: 'Resume storage is not set up' }), NOT_SET_UP],
    [
      'the store did not answer',
      () => answer(503, { detail: 'Resume storage did not answer; try again later' }),
      STORAGE_DOWN,
    ],
    ['the resume is gone', () => answer(404, { detail: 'No resume uploaded' }), NOT_SAVED],
    ['the request failed', () => Promise.reject(new TypeError('Failed to fetch')), NOT_SAVED],
  ])('says so when a save fails because %s', async (_case, reply, said) => {
    service(() => answer(200, read()), reply)
    const user = userEvent.setup()
    render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)

    await user.click(save())

    expect(await within(check()).findByText(said)).toBe(alertLine())
    expect(save()).toHaveAttribute('aria-disabled', 'false')
  })

  it.each([
    ['storage is not set up', () => answer(503, { detail: 'Resume storage is not set up' }), NOT_SET_UP],
    [
      'the store did not answer',
      () => answer(503, { detail: 'Resume storage did not answer; try again later' }),
      STORAGE_DOWN,
    ],
    ['the resume is gone', () => answer(404, { detail: 'No resume uploaded' }), NOT_LOADED],
    ['the request failed', () => Promise.reject(new TypeError('Failed to fetch')), NOT_LOADED],
  ])('says so, offering no box, when the read fails because %s', async (_case, reply, said) => {
    service(reply)

    render(<ResumeTextCheck />)

    expect(await within(check()).findByText(said)).toBe(alertLine())
    expect(screen.queryByLabelText("Your resume's text")).not.toBeInTheDocument()
    expect(status()).toHaveTextContent(/^$/)
  })

  it('cancels its read when it goes', async () => {
    const fetchMock = service(answerOnlyAbort)
    const { unmount } = render(<ResumeTextCheck />)
    await act(async () => {
      await Promise.resolve()
    })
    const init = fetchMock.mock.calls[0]?.[1]

    unmount()

    expect(init?.signal?.aborted).toBe(true)
  })

  it('cancels a save still going when it goes', async () => {
    const fetchMock = service(() => answer(200, read()))
    const user = userEvent.setup()
    const { unmount } = render(<ResumeTextCheck />)
    await within(check()).findByText(FOUND_LINE)
    await user.click(save())
    await act(async () => {
      await Promise.resolve()
    })
    const [init] = puts(fetchMock)

    unmount()

    expect(init?.signal?.aborted).toBe(true)
  })

  it('shows no failure for a read it aborted itself', async () => {
    // StrictMode mounts, unmounts and mounts again, so the first read is
    // aborted while it waits for its token, and only the second asks.
    const fetchMock = service(() => answer(200, read()))

    render(
      <StrictMode>
        <ResumeTextCheck />
      </StrictMode>,
    )

    expect(await within(check()).findByText(FOUND_LINE)).toBe(status())
    expect(clerk.getToken).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls).toHaveLength(1)
    expect(alertLine()).toHaveTextContent(/^$/)
  })
})
