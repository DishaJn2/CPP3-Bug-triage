import { useState, useEffect } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getConnections } from '../api/settings'

const NAV = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/bugs',      label: 'Bugs' },
  { to: '/history',   label: 'History' },
  { to: '/settings',  label: 'Settings' },
]

const AsteriskSvg = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
    <path d="M9 2v14M2 9h14M3.4 3.4l11.2 11.2M14.6 3.4L3.4 14.6" stroke="#fff" strokeWidth="2" strokeLinecap="round"/>
  </svg>
)

export default function TopBar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [connCount, setConnCount] = useState(0)

  useEffect(() => {
    getConnections()
      .then((list) => setConnCount(Array.isArray(list) ? list.filter((c) => c.enabled !== false).length : 0))
      .catch(() => setConnCount(0))
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link to="/bugs" style={{ display: 'flex', alignItems: 'center', textDecoration: 'none' }}>
          <div className="logo-box">
            <AsteriskSvg />
          </div>
          <div className="logo-brand">
            <strong>Bug Triage Tool</strong>
            <small>Agentic Bug Triage System</small>
          </div>
        </Link>

        <div className="topbar-sep" />

        <nav className="nav">
          {NAV.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className={`nav-link${location.pathname.startsWith(to) ? ' active' : ''}`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="topbar-right">
        <div className="sys-chip">
          <span className="sys-chip-dot" />
          {connCount} system{connCount !== 1 ? 's' : ''} connected
        </div>

        <span className="email-chip">{user?.email || '—'}</span>

        <span className="role-badge">{user?.role || 'Engineer'}</span>

        <button className="btn-logout" onClick={handleLogout}>Logout</button>
      </div>
    </header>
  )
}
