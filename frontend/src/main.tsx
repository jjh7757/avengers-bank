import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'

import App from './App'
import { AuthProvider } from './auth/AuthProvider'
import './index.css'
import './ui.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
