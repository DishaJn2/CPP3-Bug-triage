import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMetrics } from '../api/bugs'

const SOURCE_ICON = { jira_apache: 'J', bugzilla: 'BZ', github: 'GH', confluence: 'CF' }
const SOURCE_CLS  = { jira_apache: 'ci-jira', bugzilla: 'ci-bz', github: 'ci-gh', confluence: 'ci-cf' }
const SEV_CLS     = { P0: 'sev-p0', P1: 'sev-p1', P2: 'sev-p2', P3: 'sev-p3' }
const SRC_CLS     = { jira_apache: 'sb-jira', bugzilla: 'sb-bz', github: 'sb-gh', confluence: 'sb-cf' }
const SRC_LBL     = { jira_apache: 'JIRA', bugzilla: 'BZ', github: 'GH', confluence: 'CF' }

function timeAgo(iso) {
  if (!iso) return '—'
  try {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  } catch { return '—' }
}

function StatCard({ label, value, color, topBorder, sub }) {
  return (
    <div className={`stat-card ${topBorder}`}>
      <div className={`stat-val ${color}`}>{value ?? '—'}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    getMetrics().then(setMetrics).catch(console.error)
  }, [])

  const bySev     = metrics?.by_severity || {}
  const triaged   = metrics?.total_triages ?? metrics?.total_triaged ?? 0
  const critical  = (bySev.P0 || 0) + (bySev.P1 || 0)
  const pending   = (bySev.P2 || 0) + (bySev.P3 || 0)
  const online    = metrics?.sources_online ?? 0
  const recentAct = metrics?.recent_activity || []
  const avgConf   = metrics?.avg_confidence != null
    ? Math.round(metrics.avg_confidence * 100)
    : null

  return (
    <div>
      <div className="page-hdr-row">
        <div className="page-hdr">
          <h1>System Overview</h1>
          <p>Auto-discovery active · {online} source{online !== 1 ? 's' : ''} online</p>
        </div>
      </div>

      {/* Stat cards */}
      <div className="stat-grid">
        <StatCard label="Total Triages"    value={triaged}                              color="blue"   topBorder="blue-t"   sub="AI-processed" />
        <StatCard label="P0 / P1 Critical" value={critical}                             color="red"    topBorder="red-t"    sub="needs immediate action" />
        <StatCard label="Sources Online"   value={online || '—'}                        color="green"  topBorder="green-t"  sub="connected systems" />
        <StatCard label="Avg Confidence"   value={avgConf != null ? `${avgConf}%` : '—'} color="teal" topBorder="teal-t"  sub="recent triages" />
        <StatCard label="Pending P2 / P3"  value={pending}                              color="amber"  topBorder="amber-t"  sub="lower priority" />
      </div>

      {/* 2-col lower grid */}
      <div className="dash-grid">
        {/* By Source */}
        <div className="card">
          <div className="dash-panel-hdr">
            <h3>Connected Systems</h3>
            <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace' }}>{online} configured</span>
          </div>
          {Object.keys(metrics?.by_source || {}).length === 0 ? (
            <p style={{ color: 'var(--text3)', fontSize: 13, margin: 0 }}>
              {metrics ? 'No triage data yet.' : 'Loading…'}
            </p>
          ) : Object.entries(metrics.by_source).map(([srcId, count]) => (
            <div key={srcId} className="conn-item">
              <div className={`conn-icon-box ${SOURCE_CLS[srcId] || 'ci-jira'}`}>
                {SOURCE_ICON[srcId] || srcId.slice(0, 2).toUpperCase()}
              </div>
              <div className="conn-item-info">
                <strong>{srcId}</strong>
                <small>{count} triage{count !== 1 ? 's' : ''}</small>
              </div>
              <span className="status-dot ok" />
            </div>
          ))}
        </div>

        {/* Recent Triage Activity */}
        <div className="card">
          <div className="dash-panel-hdr">
            <h3>Recent Triage Activity</h3>
            <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace' }}>last {recentAct.length}</span>
          </div>
          {recentAct.length === 0 ? (
            <p style={{ color: 'var(--text3)', fontSize: 13, margin: 0 }}>No triage history yet.</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text3)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Bug ID</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Sev</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Conf</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Root Cause</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>Dur</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 600 }}>When</th>
                  <th style={{ padding: '4px 8px' }} />
                </tr>
              </thead>
              <tbody>
                {recentAct.map((entry, i) => {
                  const conf = entry.confidence ? `${(entry.confidence * 100).toFixed(0)}%` : '—'
                  const dur  = entry.duration_ms ? `${(entry.duration_ms / 1000).toFixed(1)}s` : '—'
                  return (
                    <tr key={entry.case_id || i} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '5px 8px', fontFamily: 'JetBrains Mono, monospace', color: 'var(--text2)' }}>
                        {entry.bug_id}
                      </td>
                      <td style={{ padding: '5px 8px' }}>
                        <span className={`sev ${SEV_CLS[entry.severity] || 'sev-unk'}`}>{entry.severity || '?'}</span>
                      </td>
                      <td style={{ padding: '5px 8px', color: 'var(--teal)', fontFamily: 'JetBrains Mono, monospace' }}>{conf}</td>
                      <td style={{ padding: '5px 8px', color: 'var(--text3)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {entry.root_cause || '—'}
                      </td>
                      <td style={{ padding: '5px 8px', color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'nowrap' }}>{dur}</td>
                      <td style={{ padding: '5px 8px', color: 'var(--text3)', whiteSpace: 'nowrap' }}>{timeAgo(entry.created_at)}</td>
                      <td style={{ padding: '5px 8px' }}>
                        {entry.case_id && (
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ fontSize: 11 }}
                            onClick={() => navigate(`/triage/${entry.case_id}?from=history`)}
                          >
                            View
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
