import { ServiceStatus } from './components/ServiceStatus.tsx'

function App() {
  return (
    <main>
      <h1>Job board</h1>
      <p>
        Describe the work you want, and get job postings scored against it,
        best first.
      </p>
      <ServiceStatus />
    </main>
  )
}

export default App
