import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App publishableKey={import.meta.env.VITE_CLERK_PUBLISHABLE_KEY} />
  </StrictMode>,
)
