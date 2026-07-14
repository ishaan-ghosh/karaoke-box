// Import order matters: fonts → tokens → base → App.css (via App.tsx).
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource-variable/doto/index.css'
import '@fontsource-variable/spline-sans-mono/index.css'
import './styles/tokens.css'
import './styles/base.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
