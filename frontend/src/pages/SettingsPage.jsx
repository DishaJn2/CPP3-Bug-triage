import { useState, useEffect } from 'react'
import { getConnections, addConnection, removeConnection, testConnection } from '../api/settings'

const SYSTEM_TYPES = [
  { value: 'github',      label: 'GitHub Issues' },
  { value: 'jira_apache', label: 'Apache JIRA' },
  { value: 'bugzilla',    label: 'Bugzilla' },
  { value: 'confluence',  label: 'Confluence' },
]

const BASE_URL_DEFAULTS = {
  github:      'https://api.github.com',
  jira_apache: 'https://issues.apache.org/jira',
  bugzilla:    'https://bugzilla.mozilla.org',
  confluence:  'https://cwiki.apache.org/confluence',
}

const ICON_COLORS = {
  github:      { bg: '#5B3FA0', text: '#fff' },
  jira_apache: { bg: '#1A56A0', text: '#fff' },
  bugzilla:    { bg: '#D97706', text: '#fff' },
  confluence:  { bg: '#0A7C6E', text: '#fff' },
}

const FILTER_OPTIONS = [
  { key: 'all',         label: 'All Systems',  typeKey: null },
  { key: 'github',      label: 'GitHub',       typeKey: 'github' },
  { key: 'jira_apache', label: 'Apache JIRA',  typeKey: 'jira_apache' },
  { key: 'bugzilla',    label: 'Bugzilla',     typeKey: 'bugzilla' },
  { key: 'confluence',  label: 'Confluence',   typeKey: 'confluence' },
]

const EMPTY_FORM = {
  display_name: '',
  system_type: 'github',
  base_url: BASE_URL_DEFAULTS.github,
  auth_token: '',
  project_key: '',
  ticket_prefix: '',
}

function Dot({ color }) {
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: color, marginRight: 5, flexShrink: 0,
    }} />
  )
}

function StatusIndicator({ conn }) {
  if (!conn.enabled)
    return <span style={{ display: 'flex', alignItems: 'center', fontSize: 12, color: 'var(--text3)' }}><Dot color="#9AA3B5" />Disabled</span>
  if (conn.system_type === 'jira_apache' || conn.system_type === 'bugzilla')
    return <span style={{ display: 'flex', alignItems: 'center', fontSize: 12, color: 'var(--green)' }}><Dot color="#166534" />Public API</span>
  if (conn.token_present)
    return <span style={{ display: 'flex', alignItems: 'center', fontSize: 12, color: 'var(--green)' }}><Dot color="#166534" />Connected</span>
  return <span style={{ display: 'flex', alignItems: 'center', fontSize: 12, color: 'var(--red)' }}><Dot color="#B91C1C" />No Token</span>
}

export default function SettingsPage() {
  const [connections,  setConnections]  = useState([])
  const [byType,       setByType]       = useState({})
  const [filter,       setFilter]       = useState('all')
  const [testing,      setTesting]      = useState({})
  const [testResults,  setTestResults]  = useState({})
  const [showAddModal, setShowAddModal] = useState(false)
  const [addForm,      setAddForm]      = useState(EMPTY_FORM)
  const [addLoading,   setAddLoading]   = useState(false)
  const [addError,     setAddError]     = useState('')
  const [toast,        setToast]        = useState('')

  const fetchConnections = () => {
    getConnections()
      .then((data) => {
        setConnections(data.connections || [])
        setByType(data.by_type || {})
      })
      .catch(console.error)
  }

  useEffect(() => { fetchConnections() }, [])

  const handleTest = async (sourceId) => {
    setTesting((p) => ({ ...p, [sourceId]: true }))
    try {
      const r = await testConnection(sourceId)
      setTestResults((p) => ({ ...p, [sourceId]: r }))
    } catch (err) {
      setTestResults((p) => ({
        ...p,
        [sourceId]: { status: 'error', message: err.response?.data?.detail || err.message || 'Connection failed' },
      }))
    } finally {
      setTesting((p) => ({ ...p, [sourceId]: false }))
    }
  }

  const handleRemove = async (sourceId) => {
    if (!window.confirm('Remove this connection?')) return
    try {
      await removeConnection(sourceId)
      fetchConnections()
    } catch (err) {
      alert('Failed to remove: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleAddSubmit = async (e) => {
    e.preventDefault()
    setAddLoading(true)
    setAddError('')
    try {
      await addConnection(addForm)
      setShowAddModal(false)
      setAddForm(EMPTY_FORM)
      fetchConnections()
      setToast('Connection added successfully')
      setTimeout(() => setToast(''), 3000)
    } catch (err) {
      setAddError(err.response?.data?.detail || err.message || 'Failed to add connection')
    } finally {
      setAddLoading(false)
    }
  }

  const handleSystemTypeChange = (type) => {
    setAddForm((f) => ({
      ...f,
      system_type: type,
      base_url: BASE_URL_DEFAULTS[type] || '',
    }))
  }

  const closeModal = () => { setShowAddModal(false); setAddError('') }

  const filtered = filter === 'all'
    ? connections
    : connections.filter((c) => c.system_type === filter)

  const filterLabel = FILTER_OPTIONS.find((f) => f.key === filter)?.label || 'All Systems'

  return (
    <div>
      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', top: 20, right: 20, zIndex: 9999,
          background: 'var(--green)', color: '#fff', padding: '10px 18px',
          borderRadius: 8, fontSize: 13, fontWeight: 600,
          boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        }}>
          ✓ {toast}
        </div>
      )}

      <div className="page-hdr">
        <h1>Connections</h1>
        <p>Manage source system connectors</p>
      </div>

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>

        {/* LEFT SIDEBAR */}
        <div style={{
          width: 220, flexShrink: 0,
          background: '#fff', border: '1px solid var(--border)',
          borderRadius: 10, overflow: 'hidden',
        }}>
          <div style={{
            padding: '12px 16px 8px',
            fontSize: 10.5, fontWeight: 700, color: 'var(--text3)',
            letterSpacing: '0.07em', textTransform: 'uppercase',
          }}>
            Filter by System
          </div>
          {FILTER_OPTIONS.map((opt) => {
            const count = opt.typeKey === null ? connections.length : (byType[opt.typeKey] || 0)
            const active = filter === opt.key
            return (
              <button
                key={opt.key}
                onClick={() => setFilter(opt.key)}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  width: '100%', padding: '9px 16px', textAlign: 'left',
                  border: 'none', borderRadius: 0, cursor: 'pointer', fontSize: 13.5,
                  background: active ? 'var(--teal-lt)' : 'transparent',
                  color: active ? 'var(--teal)' : 'var(--text)',
                  fontWeight: active ? 600 : 400,
                }}
              >
                <span>{opt.label}</span>
                <span style={{
                  fontSize: 11, fontWeight: 700, minWidth: 20, textAlign: 'center',
                  padding: '1px 7px', borderRadius: 10,
                  background: active ? 'var(--teal)' : 'var(--bg)',
                  color: active ? '#fff' : 'var(--text2)',
                }}>
                  {count}
                </span>
              </button>
            )
          })}
        </div>

        {/* RIGHT PANEL */}
        <div style={{ flex: 1, background: '#fff', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          {/* Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>{filterLabel}</h3>
            <button className="btn btn-teal btn-sm" onClick={() => setShowAddModal(true)}>
              + Add Connection
            </button>
          </div>

          {/* Info banner */}
          <div style={{
            background: 'var(--blue-lt)', border: '1px solid var(--blue-bd)',
            borderRadius: 8, padding: '10px 14px', marginBottom: 16,
            fontSize: 12, color: 'var(--blue)', display: 'flex', alignItems: 'flex-start', gap: 8,
          }}>
            <span style={{ flexShrink: 0, fontWeight: 700 }}>ℹ</span>
            <span>
              Connectors seeded via{' '}
              <code style={{ fontFamily: 'JetBrains Mono, monospace' }}>init_db.py</code>
              {' '}on startup. Add new connections here. Changes take effect immediately without restarting the server.
            </span>
          </div>

          {/* Connection cards */}
          {filtered.length === 0 ? (
            <p style={{ textAlign: 'center', color: 'var(--text3)', fontSize: 13, padding: '32px 0' }}>
              No connections found for this system type.
            </p>
          ) : filtered.map((conn) => {
            const ic = ICON_COLORS[conn.system_type] || { bg: '#9AA3B5', text: '#fff' }
            const testRes = testResults[conn.source_id]
            const isLoading = !!testing[conn.source_id]

            return (
              <div key={conn.source_id} style={{
                border: '1px solid var(--border)', borderRadius: 10,
                padding: 16, marginBottom: 12,
              }}>
                <div style={{ display: 'flex', alignItems: 'center' }}>
                  {/* Icon box */}
                  <div style={{
                    width: 36, height: 36, borderRadius: 8, flexShrink: 0,
                    background: ic.bg, color: ic.text,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, fontWeight: 700,
                  }}>
                    {conn.icon}
                  </div>

                  {/* Middle */}
                  <div style={{ flex: 1, margin: '0 16px', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{conn.display_name}</span>
                      {conn.ticket_prefix && (
                        <span style={{
                          fontSize: 10.5, fontFamily: 'JetBrains Mono, monospace',
                          border: '1px solid var(--teal-bd)', color: 'var(--teal)',
                          borderRadius: 4, padding: '1px 6px',
                        }}>
                          {conn.ticket_prefix}
                        </span>
                      )}
                    </div>
                    <div style={{
                      fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
                      color: 'var(--text3)', marginTop: 2,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {conn.base_url}
                    </div>
                    {conn.project_key && (
                      <div style={{ fontSize: 11.5, color: 'var(--text2)', marginTop: 1 }}>
                        {conn.project_key}
                      </div>
                    )}
                  </div>

                  {/* Right controls */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                    <StatusIndicator conn={conn} />

                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => handleTest(conn.source_id)}
                      disabled={isLoading}
                    >
                      {isLoading ? '⟳ Testing…' : 'Test'}
                    </button>

                    <button
                      className="btn btn-sm"
                      style={{ border: '1px solid var(--red-bd)', color: 'var(--red)', background: 'transparent' }}
                      onClick={() => handleRemove(conn.source_id)}
                    >
                      Remove
                    </button>
                  </div>
                </div>

                {/* Test result inline */}
                {testRes && !isLoading && (
                  <div style={{
                    marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)',
                    fontSize: 12,
                    color: testRes.status === 'ok' ? 'var(--green)' : 'var(--red)',
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>
                    {testRes.status === 'ok' ? `✓ ${testRes.message}` : `✗ ${testRes.message}`}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ADD CONNECTION MODAL */}
      {showAddModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: '#fff', borderRadius: 14, padding: 32,
            maxWidth: 480, width: '100%', margin: '0 16px',
            position: 'relative', maxHeight: '90vh', overflowY: 'auto',
          }}>
            <button
              onClick={closeModal}
              style={{
                position: 'absolute', top: 16, right: 16,
                background: 'none', border: 'none', fontSize: 22,
                cursor: 'pointer', color: 'var(--text3)', lineHeight: 1,
              }}
            >×</button>

            <h2 style={{ margin: '0 0 24px', fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>
              Add New Connection
            </h2>

            <form onSubmit={handleAddSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* System Type */}
              <div>
                <label className="form-label">System Type</label>
                <select
                  className="form-select"
                  style={{ width: '100%' }}
                  value={addForm.system_type}
                  onChange={(e) => handleSystemTypeChange(e.target.value)}
                >
                  {SYSTEM_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>

              {/* Display Name */}
              <div>
                <label className="form-label">Display Name</label>
                <input
                  className="form-input"
                  style={{ width: '100%' }}
                  placeholder="e.g. Apache Spark — GitHub"
                  value={addForm.display_name}
                  onChange={(e) => setAddForm((f) => ({ ...f, display_name: e.target.value }))}
                  required
                />
              </div>

              {/* Base URL */}
              <div>
                <label className="form-label">Base URL</label>
                <input
                  className="form-input"
                  style={{ width: '100%' }}
                  value={addForm.base_url}
                  onChange={(e) => setAddForm((f) => ({ ...f, base_url: e.target.value }))}
                  required
                />
              </div>

              {/* Auth Token */}
              <div>
                <label className="form-label">Auth Token</label>
                <input
                  className="form-input"
                  style={{ width: '100%' }}
                  type="password"
                  placeholder="Leave empty for public APIs"
                  value={addForm.auth_token}
                  onChange={(e) => setAddForm((f) => ({ ...f, auth_token: e.target.value }))}
                />
                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>
                  Not required for Apache JIRA and Bugzilla
                </div>
              </div>

              {/* Project Key */}
              <div>
                <label className="form-label">Project Key</label>
                <input
                  className="form-input"
                  style={{ width: '100%' }}
                  placeholder="e.g. apache/spark (GitHub) or SPARK (JIRA)"
                  value={addForm.project_key}
                  onChange={(e) => setAddForm((f) => ({ ...f, project_key: e.target.value }))}
                />
              </div>

              {/* Ticket Prefix */}
              <div>
                <label className="form-label">Ticket Prefix</label>
                <input
                  className="form-input"
                  style={{ width: '100%' }}
                  placeholder="e.g. SGH or SPARK"
                  value={addForm.ticket_prefix}
                  onChange={(e) => setAddForm((f) => ({ ...f, ticket_prefix: e.target.value }))}
                />
              </div>

              {addError && (
                <div style={{ color: 'var(--red)', fontSize: 13 }}>{addError}</div>
              )}

              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={closeModal}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-teal"
                  disabled={addLoading}
                >
                  {addLoading ? 'Saving…' : 'Save & Test'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
