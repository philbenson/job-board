import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  ResumeBody,
  StorageRefusalBody,
  UploadedBody,
  UploadRefusalBody,
} from '../api/resume.ts'
import type { ResumeTextBody } from '../api/resumeText.ts'
import { ResumePanel } from './ResumePanel.tsx'

// Clerk replaced by a stand-in that hands out a session token, so no test
// reaches Clerk's servers.
const clerk = vi.hoisted(() => ({
  getToken: vi.fn<() => Promise<string | null>>(),
}))

vi.mock('@clerk/react', () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: clerk.getToken }),
}))

const SESSION_TOKEN = 'header.payload.signature'
const LARGEST = 5 * 1024 * 1024

const LOADING = 'Loading your resume…'
const NOT_LOADED = 'Could not load your resume'
const NONE_YET = 'No resume yet'
const UPLOADING = 'Uploading and reading your resume…'
const UPLOADED = 'Resume uploaded'
const REMOVING = 'Removing your resume…'
const REMOVED = 'Resume removed'
const TOO_LARGE = 'A resume can be at most 5 MB'
const NOT_A_PDF = 'That file is not a PDF'
const CHOOSE_FIRST = 'Choose a PDF first'
const NOT_SET_UP = 'Resume storage is not set up on this service yet'
const STORAGE_DOWN = 'Could not reach resume storage; try again later'
const NOT_UPLOADED = 'Could not upload your resume'
const READING_BUSY = 'The service is busy reading resumes. Try again in a minute.'
const NOT_REMOVED = 'Could not remove your resume'
const NOT_READ = 'Could not read that file; choose it again'

const EARLIER = '2026-11-01T09:30:00Z'
const LATER = '2026-11-07T20:29:59.747970Z'

// On one line each, since a display value is matched with its spaces collapsed.
const TEXT_READ = 'Avery Example, Staff Engineer at Example Widgets'
const NEW_TEXT_READ = 'Avery Example, Principal Engineer at Example Widgets'

// The page's own way of writing a time, so the tests hold in any locale and
// time zone they run in.
function shownTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

function held(sizeBytes: number, uploadedAt: string): ResumeBody {
  return { resume: { size_bytes: sizeBytes, uploaded_at: uploadedAt } }
}

// What an upload answers, typed by the upload's own answer.
function recorded(sizeBytes: number, uploadedAt: string): UploadedBody {
  return { resume: { size_bytes: sizeBytes, uploaded_at: uploadedAt } }
}

const NONE = { resume: null } satisfies ResumeBody
const STORAGE_NOT_SET_UP = {
  detail: 'Resume storage is not set up',
} satisfies StorageRefusalBody
const DID_NOT_ANSWER = {
  detail: 'Resume storage did not answer; try again later',
} satisfies StorageRefusalBody
const BUSY = {
  detail: 'Resume reading is busy; try again in a minute',
} satisfies UploadRefusalBody

// A body the contract allows, typed so it changes when the backend's does.
function answer(
  status: number,
  body: ResumeBody | UploadedBody | StorageRefusalBody | UploadRefusalBody,
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

// The resume route answers a read with `read`, an upload, a removal and a read
// of the resume's text as the test says; until a test says, they never answer.
function service(
  read: Reply,
  answers: { upload?: Reply; remove?: Reply; text?: Reply } = {},
) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url === '/api/resume/text') {
      return (answers.text ?? answerOnlyAbort)(init)
    }
    if (url !== '/api/resume') {
      return Promise.reject(new TypeError(`unexpected request to ${url}`))
    }
    if (init?.method === 'PUT') {
      return (answers.upload ?? answerOnlyAbort)(init)
    }
    if (init?.method === 'DELETE') {
      return (answers.remove ?? answerOnlyAbort)(init)
    }
    return read(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sent(fetchMock: ReturnType<typeof service>, method: string): RequestInit[] {
  return fetchMock.mock.calls
    .map(([, init]) => init)
    .filter((init): init is RequestInit => init?.method === method)
}

function pdf(size: number, name = 'resume.pdf'): File {
  const bytes = new Uint8Array(size)
  bytes.set(new TextEncoder().encode('%PDF-1.7\n'))
  return new File([bytes], name, { type: 'application/pdf' })
}

function chooser(): HTMLInputElement {
  return screen.getByLabelText<HTMLInputElement>('Choose a PDF')
}

// The panel's own status line, not the one its text check holds.
function status(): HTMLElement {
  const check = screen.queryByRole('region', { name: 'Resume text' })
  const lines = screen.getAllByRole('status').filter((line) => check?.contains(line) !== true)
  expect(lines).toHaveLength(1)
  return lines[0] as HTMLElement
}

function textRead(text: string, uploadedAt: string): Promise<Response> {
  const body: ResumeTextBody = { uploaded_at: uploadedAt, state: 'found', text, checked_at: null }
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
}

async function loaded(): Promise<void> {
  expect(await screen.findByLabelText('Choose a PDF')).toBeInTheDocument()
}

describe('ResumePanel', () => {
  beforeEach(() => {
    clerk.getToken.mockReset()
    clerk.getToken.mockResolvedValue(SESSION_TOKEN)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('says it is loading, then that there is no resume yet', async () => {
    const fetchMock = service(() => answer(200, NONE))

    render(<ResumePanel />)

    expect(screen.getByRole('heading', { level: 2, name: 'Resume' })).toBeInTheDocument()
    expect(screen.getByText(LOADING)).toBeInTheDocument()
    await loaded()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    expect(chooser()).toHaveAttribute('accept', 'application/pdf,.pdf')
    // The status line is on the page, empty, so what it later says is announced.
    expect(status()).toHaveTextContent(/^$/)
    const init = fetchMock.mock.calls[0]?.[1]
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)
  })

  it.each([
    [2064, '2 KB'],
    [1023, '1 KB'],
    [1024 * 1024 - 1, '1023 KB'],
    [1024 * 1024, '1.0 MB'],
    [1572864, '1.5 MB'],
    [LARGEST, '5.0 MB'],
  ])('shows a resume of %i bytes as %s, with when it was uploaded', async (size, shown) => {
    service(() => answer(200, held(size, EARLIER)))

    render(<ResumePanel />)
    await loaded()

    expect(screen.getByText(`${shown}, uploaded ${shownTime(EARLIER)}`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
  })

  it('says storage is not set up, and offers nothing to do, when the service has none', async () => {
    service(() => answer(503, STORAGE_NOT_SET_UP))

    render(<ResumePanel />)

    expect(await screen.findByText(NOT_SET_UP)).toBeInTheDocument()
    expect(screen.queryByLabelText('Choose a PDF')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says it could not load the resume when the service does not answer', async () => {
    service(() => Promise.reject(new TypeError('Failed to fetch')))

    render(<ResumePanel />)

    expect(await screen.findByText(NOT_LOADED)).toBeInTheDocument()
    expect(screen.queryByLabelText('Choose a PDF')).not.toBeInTheDocument()
  })

  it('uploads the chosen file as it is, holding the button while it goes, then shows it', async () => {
    let answerUpload: (response: Response) => void = () => {}
    const fetchMock = service(() => answer(200, NONE), {
      upload: () =>
        new Promise<Response>((resolve) => {
          answerUpload = resolve
        }),
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()
    const file = pdf(2064)

    await user.upload(chooser(), file)
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    expect(await screen.findByText(UPLOADING)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveAttribute('aria-disabled', 'true')
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(sent(fetchMock, 'PUT')).toHaveLength(1)

    await act(async () => {
      answerUpload(
        new Response(JSON.stringify(recorded(2064, LATER)), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      await Promise.resolve()
    })

    expect(await screen.findByText(UPLOADED)).toBeInTheDocument()
    expect(screen.getByText(`2 KB, uploaded ${shownTime(LATER)}`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace' })).toHaveAttribute('aria-disabled', 'false')
    const [init] = sent(fetchMock, 'PUT')
    expect(init?.body).toBe(file)
    const headers = new Headers(init?.headers)
    expect(headers.get('Content-Type')).toBe('application/pdf')
    expect(headers.get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)
  })

  it('replaces a resume already there', async () => {
    const fetchMock = service(() => answer(200, held(2064, EARLIER)), {
      upload: () => answer(200, recorded(LARGEST, LATER)),
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    await user.upload(chooser(), pdf(LARGEST))
    await user.click(screen.getByRole('button', { name: 'Replace' }))

    expect(await screen.findByText(`5.0 MB, uploaded ${shownTime(LATER)}`)).toBeInTheDocument()
    expect(status()).toHaveTextContent(UPLOADED)
    expect(sent(fetchMock, 'PUT')).toHaveLength(1)
  })

  it.each([
    ['a file over 5 MB', () => pdf(LARGEST + 1), TOO_LARGE],
    [
      'a file that does not start as a PDF does',
      () => new File(['GIF89a'], 'resume.pdf', { type: 'application/pdf' }),
      NOT_A_PDF,
    ],
    ['a file shorter than a PDF can be', () => new File(['%PDF'], 'resume.pdf'), NOT_A_PDF],
    ['an empty file', () => new File([], 'resume.pdf'), NOT_A_PDF],
  ])('refuses %s at once, sending nothing', async (_case, file, refusal) => {
    const fetchMock = service(() => answer(200, NONE))
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    await user.upload(chooser(), file())
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    expect(await screen.findByText(refusal)).toBeInTheDocument()
    expect(sent(fetchMock, 'PUT')).toEqual([])
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
  })

  it.each([
    ['fails', () => answer(503, { detail: 'down' }), NOT_UPLOADED, EARLIER],
    ['succeeds', () => answer(200, recorded(2064, LATER)), UPLOADED, LATER],
  ])('sends a file chosen while an upload is out when the first %s', async (_case, first, said, shownAt) => {
    let answerFirst: () => void = () => {}
    const fetchMock = service(() => answer(200, held(2064, EARLIER)), {
      upload: () => {
        if (sent(fetchMock, 'PUT').length > 1) {
          return answer(200, recorded(4096, LATER))
        }
        return new Promise<Response>((resolve) => {
          answerFirst = () => {
            void first().then(resolve)
          }
        })
      },
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()
    const second = pdf(4096, 'second.pdf')

    await user.upload(chooser(), pdf(2064, 'first.pdf'))
    await user.click(screen.getByRole('button', { name: 'Replace' }))
    await screen.findByText(UPLOADING)
    await user.upload(chooser(), second)
    // Choosing while a request is out leaves its status line alone.
    expect(status()).toHaveTextContent(UPLOADING)
    await act(async () => {
      answerFirst()
      await Promise.resolve()
    })
    expect(await screen.findByText(said)).toBeInTheDocument()
    expect(screen.getByText(`2 KB, uploaded ${shownTime(shownAt)}`)).toBeInTheDocument()
    expect(chooser().files?.[0]).toBe(second)
    await user.click(screen.getByRole('button', { name: 'Replace' }))

    expect(await screen.findByText(`4 KB, uploaded ${shownTime(LATER)}`)).toBeInTheDocument()
    const puts = sent(fetchMock, 'PUT')
    expect(puts).toHaveLength(2)
    expect(puts[1]?.body).toBe(second)
  })

  it('says so when the chosen file can no longer be read, sending nothing', async () => {
    const fetchMock = service(() => answer(200, NONE))
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()
    // What a browser does when the file changed or went on disk after it was chosen.
    const changed = pdf(2064)
    changed.slice = () =>
      ({
        arrayBuffer: () => Promise.reject(new DOMException('changed on disk', 'NotReadableError')),
      }) as unknown as Blob

    await user.upload(chooser(), changed)
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    expect(await screen.findByText(NOT_READ)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveAttribute('aria-disabled', 'false')
    expect(sent(fetchMock, 'PUT')).toEqual([])
  })

  it('asks for a file when Upload is pressed before one is chosen', async () => {
    const fetchMock = service(() => answer(200, NONE))
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    await user.click(screen.getByRole('button', { name: 'Upload' }))

    expect(status()).toHaveTextContent(CHOOSE_FIRST)
    expect(sent(fetchMock, 'PUT')).toEqual([])
  })

  it.each([
    ['storage is not set up', () => answer(503, STORAGE_NOT_SET_UP), NOT_SET_UP],
    ['the store did not answer', () => answer(503, DID_NOT_ANSWER), STORAGE_DOWN],
    ['reading is busy', () => answer(503, BUSY), READING_BUSY],
    ['the service answered something else', () => answer(503, { detail: 'down' }), NOT_UPLOADED],
    ['the request failed', () => Promise.reject(new TypeError('Failed to fetch')), NOT_UPLOADED],
  ])('says so when an upload fails because %s, keeping what was there', async (_case, reply, said) => {
    service(() => answer(200, held(2064, EARLIER)), { upload: reply })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    await user.upload(chooser(), pdf(4096))
    await user.click(screen.getByRole('button', { name: 'Replace' }))

    expect(await screen.findByText(said)).toBeInTheDocument()
    expect(screen.getByText(`2 KB, uploaded ${shownTime(EARLIER)}`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace' })).toHaveAttribute('aria-disabled', 'false')
  })

  it('removes the resume without asking, holding the buttons while it goes', async () => {
    let answerRemoval: (response: Response) => void = () => {}
    const fetchMock = service(() => answer(200, held(2064, EARLIER)), {
      remove: () =>
        new Promise<Response>((resolve) => {
          answerRemoval = resolve
        }),
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    await user.click(screen.getByRole('button', { name: 'Remove' }))

    expect(await screen.findByText(REMOVING)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'Replace' })).toHaveAttribute('aria-disabled', 'true')
    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(sent(fetchMock, 'DELETE')).toHaveLength(1)

    await act(async () => {
      answerRemoval(new Response(null, { status: 204 }))
      await Promise.resolve()
    })

    expect(await screen.findByText(REMOVED)).toBeInTheDocument()
    expect(screen.getByText(NONE_YET)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveAttribute('aria-disabled', 'false')
    const [init] = sent(fetchMock, 'DELETE')
    expect(new Headers(init?.headers).get('Authorization')).toBe(`Bearer ${SESSION_TOKEN}`)
  })

  it('moves focus to the file chooser once the resume is removed', async () => {
    service(() => answer(200, held(2064, EARLIER)), {
      remove: () => Promise.resolve(new Response(null, { status: 204 })),
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    screen.getByRole('button', { name: 'Remove' }).focus()
    await user.keyboard('{Enter}')

    expect(await screen.findByText(REMOVED)).toBeInTheDocument()
    expect(chooser()).toHaveFocus()
  })

  it.each([
    ['storage is not set up', () => answer(503, STORAGE_NOT_SET_UP), NOT_SET_UP],
    ['the store did not answer', () => answer(503, DID_NOT_ANSWER), STORAGE_DOWN],
    ['the request failed', () => Promise.reject(new TypeError('Failed to fetch')), NOT_REMOVED],
  ])('says so when a removal fails because %s, keeping the resume', async (_case, reply, said) => {
    service(() => answer(200, held(2064, EARLIER)), { remove: reply })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()

    await user.click(screen.getByRole('button', { name: 'Remove' }))

    expect(await screen.findByText(said)).toBeInTheDocument()
    expect(screen.getByText(`2 KB, uploaded ${shownTime(EARLIER)}`)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove' })).toHaveAttribute('aria-disabled', 'false')
  })

  it('gives up on an upload after two and a half minutes, the session token included', async () => {
    vi.useFakeTimers()
    service(() => answer(200, NONE))
    render(<ResumePanel />)
    await act(() => vi.advanceTimersByTimeAsync(0))
    // The session token for the upload never comes.
    clerk.getToken.mockReturnValue(new Promise<string | null>(() => {}))

    fireEvent.change(chooser(), { target: { files: [pdf(2064)] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
    await act(() => vi.advanceTimersByTimeAsync(149_999))
    expect(status()).toHaveTextContent(UPLOADING)
    await act(() => vi.advanceTimersByTimeAsync(1))

    expect(status()).toHaveTextContent(NOT_UPLOADED)
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveAttribute('aria-disabled', 'false')
  })

  it('cancels an upload still going when the panel goes', async () => {
    const fetchMock = service(() => answer(200, NONE))
    const user = userEvent.setup()
    const { unmount } = render(<ResumePanel />)
    await loaded()

    await user.upload(chooser(), pdf(2064))
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    await screen.findByText(UPLOADING)
    await act(async () => {
      await Promise.resolve()
    })
    const [init] = sent(fetchMock, 'PUT')
    unmount()

    expect(init?.signal?.aborted).toBe(true)
  })

  it('offers the text check once a resume is held, and none before', async () => {
    service(() => answer(200, NONE), {
      upload: () => answer(200, recorded(2064, LATER)),
      text: () => textRead(TEXT_READ, LATER),
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()
    expect(screen.queryByRole('region', { name: 'Resume text' })).not.toBeInTheDocument()

    await user.upload(chooser(), pdf(2064))
    await user.click(screen.getByRole('button', { name: 'Upload' }))

    const check = await screen.findByRole('region', { name: 'Resume text' })
    expect(await within(check).findByLabelText("Your resume's text")).toHaveValue(TEXT_READ)
  })

  it('reads the text again for a new upload, dropping what was typed for the old file', async () => {
    const fetchMock = service(() => answer(200, held(2064, EARLIER)), {
      upload: () => answer(200, recorded(4096, LATER)),
      text: () =>
        sent(fetchMock, 'PUT').length === 0
          ? textRead(TEXT_READ, EARLIER)
          : textRead(NEW_TEXT_READ, LATER),
    })
    const user = userEvent.setup()
    render(<ResumePanel />)
    await loaded()
    const box = await screen.findByLabelText<HTMLTextAreaElement>("Your resume's text")
    await screen.findByDisplayValue(TEXT_READ)
    fireEvent.change(box, { target: { value: 'typed for the old file' } })

    await user.upload(chooser(), pdf(4096))
    await user.click(screen.getByRole('button', { name: 'Replace' }))

    expect(await screen.findByDisplayValue(NEW_TEXT_READ)).toBe(
      screen.getByLabelText("Your resume's text"),
    )
    expect(screen.queryByDisplayValue('typed for the old file')).not.toBeInTheDocument()
    const textReads = fetchMock.mock.calls.filter(([url]) => url === '/api/resume/text')
    expect(textReads).toHaveLength(2)
  })
})
