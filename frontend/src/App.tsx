import { ClerkProvider } from '@clerk/react'
import type { ReactNode } from 'react'
import { Account } from './components/Account.tsx'
import { ServiceStatus } from './components/ServiceStatus.tsx'

type AppProps = {
  /** Clerk's publishable key; without one the app runs with sign-in off. */
  publishableKey: string | undefined
}

function App({ publishableKey }: AppProps) {
  const key = publishableKey?.trim()
  // Without a key Clerk is never mounted: it could not load, so its controls
  // would render nothing and never say why.
  if (!key) {
    return (
      <Page>
        <p>
          Sign-in is not configured: set <code>VITE_CLERK_PUBLISHABLE_KEY</code>{' '}
          to turn it on.
        </p>
      </Page>
    )
  }
  return (
    <ClerkProvider publishableKey={key}>
      <Page>
        <Account />
      </Page>
    </ClerkProvider>
  )
}

function Page({ children }: { children: ReactNode }) {
  return (
    <main>
      <h1>Job board</h1>
      <p>
        Describe the work you want, and get job postings scored against it,
        best first.
      </p>
      <ServiceStatus />
      {children}
    </main>
  )
}

export default App
