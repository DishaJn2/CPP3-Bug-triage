import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { AuthProvider } from './context/AuthContext'
import { ToastProvider } from './context/ToastContext'
import { BugListCacheProvider } from './context/BugListCacheContext'
import './styles/main.css'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <ToastProvider>
        <BugListCacheProvider>
          <App />
        </BugListCacheProvider>
      </ToastProvider>
    </AuthProvider>
  </React.StrictMode>
)
