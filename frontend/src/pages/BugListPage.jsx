import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBugs, getBugStatus, refreshBugCache } from '../api/bugs'
import { startTriage } from '../api/triage'

const SRC_CLS = { github: 'sb-gh', jira_apache: 'sb-jira', bugzilla: 'sb-bz', confluence: 'sb-cf' }
const SRC_LBL = { github: 'GH', jira_apache: 'JIRA', bugzilla: 'BZ', confluence: 'CF' }
const SEV_CLS = { P0: 'sev-p0', P1: 'sev-p1', P2: 'sev-p2', P3: 'sev-p3' }
const SEVERITY_ORDER = ['P0', 'P1', 'P2', 'P3', 'Unknown']
const ALL_SOURCES = ['All Sources', 'github', 'jira_apache', 'bugzilla', 'confluence']

function SevBadge({ sev }) {
  return <span className={`sev ${SEV_CLS[sev] || 'sev-unk'}`}>{sev || 'UNK'}</span>
}

function SrcBadge({ type }) {
  return <span className={`sb ${SRC_CLS[type] || 'sb-jira'}`}>{SRC_LBL[type] || (type || '?').toUpperCase().slice(0, 4)}</span>
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch { return '—' }
}

/* ─── Expanded status panel (SD7 / SD8 / SD9) ─── */
function BugStatusPanel({ bugId, status, loading, onTriage, onView, triaging }) {
  if (loading) {
    return (
      <div style={{
        background: 'var(--bg)', borderTop: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', flexDirection: 'column', gap: 6,
      }}>
        <div className="skeleton-pulse" style={{ width: 180, height: 13, borderRadius: 3 }} />
        <div className="skeleton-pulse" style={{ width: 120, height: 13, borderRadius: 3 }} />
      </div>
    )
  }

  if (!status) return null

  // SD9 — never triaged
  if (status.is_new) {
    return (
      <div style={{
        background: 'var(--bg)', borderTop: '1px solid var(--border)',
        padding: '12px 24px', display: 'flex', alignItems: 'center', gap: 14,
      }}>
        <span style={{ fontSize: 13, color: 'var(--text3)' }}>Never triaged</span>
        <button
          className="btn btn-teal btn-sm"
          onClick={() => onTriage(bugId)}
          disabled={triaging === bugId}
        >
          {triaging === bugId ? '…' : '▶ Triage'}
        </button>
      </div>
    )
  }
  const lastDate = fmtDate(status.last_triaged_at)
  const confPct = status.last_confidence ? Math.round(status.last_confidence * 100) : null

  // SD7 — changes found
  if (status.needs_retriage && status.changes?.length > 0) {
    return (
      <div style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)', padding: '12px 24px' }}>
        <div style={{
          background: 'var(--orange-lt)', border: '1px solid var(--orange-bd)',
          borderRadius: 7, padding: '9px 12px', marginBottom: 10, fontSize: 12, color: 'var(--orange)',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>⚠ Changes detected since last triage:</div>
          {status.changes.map((c, i) => (
            <div key={i} style={{ marginLeft: 8 }}>• {c}</div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace', marginBottom: 10 }}>
          Last triaged: {lastDate}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {status.case_id && (
            <button className="btn btn-outline btn-sm" onClick={() => onView(status.case_id)}>
              View Previous Results
            </button>
          )}
          <button
            className="btn btn-teal btn-sm"
            onClick={() => onTriage(bugId)}
            disabled={triaging === bugId}
          >
            {triaging === bugId ? '…' : '▶ Run Fresh Triage'}
          </button>
        </div>
      </div>
    )
  }
  // SD8 — no changes
  return (
    <div style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)', padding: '12px 24px' }}>
      <div style={{ fontSize: 13, color: 'var(--green)', fontWeight: 600, marginBottom: 5 }}>
        ✓ No changes since last triage
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace', marginBottom: 10 }}>
        Last triaged: {lastDate}{confPct != null ? ` · Confidence: ${confPct}%` : ''}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        {status.case_id && (
          <button className="btn btn-outline btn-sm" onClick={() => onView(status.case_id)}>
            View Previous Results
          </button>
        )}
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => onTriage(bugId)}
          disabled={triaging === bugId}
        >
          {triaging === bugId ? '…' : 'Re-triage Anyway'}
        </button>
      </div>
    </div>
  )
}
/* ─── Expandable flat bug row (untriaged) ─── */
function ExpandableBugRow({ bug, onTriage, triaging, navigate }) {
  const [expanded,      setExpanded]      = useState(false)
  const [status,        setStatus]        = useState(null)
  const [statusLoading, setStatusLoading] = useState(false)

  const handleExpand = async () => {
    const next = !expanded
    setExpanded(next)
    if (next && !status) {
      setStatusLoading(true)
      try {
        const s = await getBugStatus(bug.ticket_id)
        setStatus(s)
      } catch {
        setStatus({ is_new: true, needs_retriage: true, changes: [] })
      } finally {
        setStatusLoading(false)
      }
    }
  }

  const handleView = (caseId) => navigate(`/triage/${caseId}?from=history`)

  return (
    <div style={{
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 8, marginBottom: 5, overflow: 'hidden',
    }}>
      <div className="bug-flat" style={{ borderRadius: 0, border: 'none', marginBottom: 0 }}>
        <button
          onClick={handleExpand}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            fontSize: 10, color: 'var(--text3)', padding: '2px 4px', flexShrink: 0,
          }}
        >
          {expanded ? '▼' : '▶'}
        </button>
        <SrcBadge type={bug.system_type} />
        <span className="raw-id">{bug.ticket_id}</span>
        <span className="bug-flat-title">{bug.title}</span>
        <SevBadge sev={bug.severity} />
        <span className="bug-status-pill">{bug.status || 'open'}</span>
        <span className="bug-flat-time">
          {bug.updated_at ? new Date(bug.updated_at).toLocaleDateString() : '—'}
        </span>
        <button
          className="btn btn-teal btn-sm"
          onClick={() => onTriage(bug.ticket_id)}
          disabled={triaging === bug.ticket_id}
        >
          {triaging === bug.ticket_id ? '…' : '▶ Triage'}
        </button>
      </div>
      {expanded && (
        <BugStatusPanel
          bugId={bug.ticket_id}
          status={status}
          loading={statusLoading}
          onTriage={onTriage}
          onView={handleView}
          triaging={triaging}
        />
      )}
    </div>
  )
}

function TriagedGroup({ group, onRetriage, retriaging }) {
  const [open, setOpen] = useState(false)
  const hasChanged = group.children?.some((c) => c.changed)

  return (
    <div className={`tree-group ${hasChanged ? 'tree-group-changed' : 'tree-group-current'}`}>
      <div className="tree-root" onClick={() => setOpen((v) => !v)}>
        <span className={`expand-arrow ${open ? 'open' : ''}`}>▶</span>
        <span className="bt-badge">{group.btId}</span>
        {group.sources?.map((s) => <SrcBadge key={s} type={s} />)}
        <span className="bug-flat-title">{group.title}</span>
        <SevBadge sev={group.severity} />
        <span className="bug-status-pill">{group.status}</span>
        {hasChanged
          ? <span className="changed-badge">⚠ Changed</span>
          : <span className="current-badge">✓ Current</span>
        }
        <span className="bug-flat-time">{group.date}</span>
        <button
          className="btn btn-outline btn-sm"
          onClick={(e) => { e.stopPropagation(); onRetriage(group.rootId) }}
          disabled={retriaging === group.rootId}
        >
          {retriaging === group.rootId ? '…' : 'Re-triage'}
        </button>
      </div>

      {open && group.children?.length > 0 && (
        <div className="tree-children">
          {group.children.map((child, i) => {
            const score = child.similarity ?? 0
            const matchCls = score >= 0.8 ? 'match-h' : score >= 0.6 ? 'match-m' : 'match-l'
            const matchLbl = `${(score * 100).toFixed(0)}% match`
            return (
              <div key={i} className="tree-child">
                <span className="tree-connector">└─</span>
                <SrcBadge type={child.system_type} />
                <span className="raw-id">{child.ticket_id}</span>
                {score > 0 && <span className={`match-badge ${matchCls}`}>{matchLbl}</span>}
                <span className="child-title">{child.title}</span>
                <SevBadge sev={child.severity} />
                <span className="bug-status-pill">{child.status}</span>
                {child.url && (
                  <a href={child.url} target="_blank" rel="noopener noreferrer" className="ext-btn">↗ Open</a>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function BugListPage() {
  const [bugs,         setBugs]         = useState([])
  const [total,        setTotal]        = useState(0)
  const [page,         setPage]         = useState(1)
  const [loading,      setLoading]      = useState(true)
  const [searchInput,  setSearchInput]  = useState('')
  const [search,       setSearch]       = useState('')
  const [severity,     setSeverity]     = useState('')
  const [source,       setSource]       = useState('')
  const [activePill,   setActivePill]   = useState('All')
  const [triagingId,   setTriagingId]   = useState(null)
  const [lastSynced,   setLastSynced]   = useState(null)
  const [directBugId,  setDirectBugId]  = useState('')
  const [refreshing,   setRefreshing]   = useState(false)
  const [sourcesOnline, setSourcesOnline] = useState(0)
  const [isPartial,    setIsPartial]    = useState(false)
  const navigate    = useNavigate()
  const intervalRef = useRef(null)

  // Debounce searchInput → search by 500 ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput)
      setPage(1)
    }, 500)
    return () => clearTimeout(timer)
  }, [searchInput])

  const fetchBugs = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getBugs({ page, severity, source: source || undefined, search })
      setBugs(data.bugs || [])
      setTotal(data.total || 0)
      setSourcesOnline(data.sources_online || 0)
      setIsPartial(data.partial || false)
      setLastSynced(new Date())
    } catch (e) {
      console.error('Failed to fetch bugs', e)
    } finally {
      setLoading(false)
    }
  }, [page, severity, source, search])

  useEffect(() => {
    fetchBugs()
    intervalRef.current = setInterval(fetchBugs, 120000)
    return () => clearInterval(intervalRef.current)
  }, [fetchBugs])

  const handleTriage = async (bugId) => {
    setTriagingId(bugId)
    try {
      const data = await startTriage(bugId)
      navigate(`/triage/${data.case_id}`)
    } catch (e) {
      alert('Failed to start triage: ' + (e.response?.data?.detail || e.message))
    } finally {
      setTriagingId(null)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refreshBugCache() } catch { /* ignore if endpoint errors */ }
    await new Promise((r) => setTimeout(r, 3000))
    await fetchBugs()
    setRefreshing(false)
  }

  const syncMinsAgo = lastSynced ? Math.round((Date.now() - lastSynced) / 60000) : null

  const triaged  = bugs.filter((b) => b.group_id || b.case_id).length
  const awaiting = bugs.length - triaged
  const start    = (page - 1) * 50 + 1
  const end      = Math.min((page - 1) * 50 + bugs.length, total)

  const visibleBugs = bugs.filter((b) => {
    if (activePill === 'All')       return true
    if (activePill === 'Untriaged') return !b.group_id && !b.case_id
    if (activePill === 'Changed')   return b.changed
    if (activePill === 'Critical')  return b.severity === 'P0' || b.severity === 'P1'
    return true
  })

  const groups = {}
  const flatBugs = []
  visibleBugs.forEach((bug) => {
    const gId = bug.group_id || bug.case_id
    if (gId) {
      if (!groups[gId]) {
        groups[gId] = {
          btId:    `BT-${gId.slice(-5).toUpperCase()}`,
          rootId:  bug.ticket_id,
          title:   bug.title,
          severity:bug.severity,
          status:  bug.status,
          sources: [],
          date:    bug.updated_at ? new Date(bug.updated_at).toLocaleDateString() : '—',
          children:[],
        }
      }
      if (bug.system_type && !groups[gId].sources.includes(bug.system_type))
        groups[gId].sources.push(bug.system_type)
      groups[gId].children.push(bug)
    } else {
      flatBugs.push(bug)
    }
  })

  return (
    <div>
      {/* Header */}
      <div className="page-hdr-row">
        <div className="page-hdr">
          <h1>Auto-Discovered Bugs</h1>
          <p>{total} bugs · fetched live · Redis cache 2 min TTL · nothing stored</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, alignSelf: 'flex-start', paddingTop: 4 }}>
          {syncMinsAgo !== null && (
            <span style={{ fontSize: 12, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace' }}>
              ↺ Synced {syncMinsAgo} min ago
            </span>
          )}
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleRefresh}
            disabled={refreshing || loading}
            title="Clear cache and reload from external systems"
            style={{ fontFamily: 'inherit' }}
          >
            {refreshing ? 'Refreshing…' : '↺ Refresh'}
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <div className="search-wrap">
          <span className="search-icon">🔍</span>
          <input
            className="form-input search-input"
            placeholder="Search by ID, title, keyword..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>

        <select className="form-select filter-select" style={{ width: 'auto' }} onChange={() => setPage(1)}>
          <option>All Projects</option>
        </select>

        <select
          className="form-select filter-select"
          style={{ width: 'auto' }}
          value={source}
          onChange={(e) => { setSource(e.target.value === 'All Sources' ? '' : e.target.value); setPage(1) }}
        >
          {ALL_SOURCES.map((s) => <option key={s} value={s === 'All Sources' ? '' : s}>{s}</option>)}
        </select>

        <select
          className="form-select filter-select"
          style={{ width: 'auto' }}
          value={severity}
          onChange={(e) => { setSeverity(e.target.value); setPage(1) }}
        >
          <option value="">All Severities</option>
          {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <div className="filter-pills">
          {['All', 'Untriaged', '⚠ Changed', 'Critical'].map((p) => (
            <button
              key={p}
              className={`pill${activePill === p || (p === '⚠ Changed' && activePill === 'Changed') ? ' active' : ''}`}
              onClick={() => setActivePill(p === '⚠ Changed' ? 'Changed' : p)}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Direct Triage bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <input
          className="form-input"
          style={{ flex: 1, maxWidth: 320 }}
          placeholder="Enter bug ID to triage directly..."
          value={directBugId}
          onChange={(e) => setDirectBugId(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && directBugId.trim()) handleTriage(directBugId.trim())
          }}
        />
        <button
          className="btn btn-teal btn-sm"
          disabled={!directBugId.trim() || triagingId === directBugId.trim()}
          onClick={() => handleTriage(directBugId.trim())}
        >
          {triagingId === directBugId.trim() ? '…' : 'Triage'}
        </button>
      </div>

      {/* Legend bar */}
      <div className="card" style={{ padding: '10px 14px', marginBottom: 10 }}>
        <div className="legend-bar">
          <span className="legend-key">KEY:</span>
          <span className="bt-badge">BT-001</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= tool group ID</span>
          <span className="changed-badge">⚠ Changed</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= updated since triage</span>
          <span className="match-badge match-h">97% match</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= AI similarity score</span>
          <span className="raw-id">DISK-779</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= raw ID not yet triaged</span>
        </div>
      </div>

      {/* Stats line */}
      {!loading && (
        <div className="stats-line">
          Showing {start}–{end} of {total} bugs · {triaged} triaged · {awaiting} awaiting · Sort: Severity
        </div>
      )}

      {/* Partial results banner */}
      {!loading && isPartial && bugs.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
          background: 'var(--orange-lt)', border: '1px solid var(--orange-bd)',
          borderRadius: 7, padding: '8px 14px', fontSize: 12, color: 'var(--orange)',
        }}>
          <span style={{ flex: 1 }}>
            ⚠ Showing partial results — some sources are still loading ({sourcesOnline} of {sourcesOnline} responded)
          </span>
          <button className="btn btn-ghost btn-sm" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      )}

      {/* Bug rows */}
      {loading ? (
        <div>
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bug-flat" style={{ opacity: 1 }}>
              <div className="skeleton-pulse" style={{ width: 32, height: 18, borderRadius: 4 }} />
              <div className="skeleton-pulse" style={{ width: 80, height: 14, borderRadius: 3 }} />
              <div className="skeleton-pulse" style={{ flex: 1, height: 14, borderRadius: 3 }} />
              <div className="skeleton-pulse" style={{ width: 36, height: 18, borderRadius: 4 }} />
              <div className="skeleton-pulse" style={{ width: 56, height: 18, borderRadius: 4 }} />
              <div className="skeleton-pulse" style={{ width: 64, height: 14, borderRadius: 3 }} />
              <div className="skeleton-pulse" style={{ width: 72, height: 28, borderRadius: 5 }} />
            </div>
          ))}
        </div>
      ) : visibleBugs.length === 0 ? (
        (() => {
          const hasFilters = !!(search || severity || source || activePill !== 'All')
          if (hasFilters) {
            return (
              <div className="card" style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)', fontSize: 13 }}>
                <div style={{ marginBottom: 12 }}>No bugs match the current filter.</div>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setSearchInput('')
                    setSearch('')
                    setSeverity('')
                    setSource('')
                    setActivePill('All')
                    setPage(1)
                  }}
                >
                  Clear filters
                </button>
              </div>
            )
          }
          return (
            <div className="card" style={{ textAlign: 'center', padding: '40px' }}>
              <div style={{ fontSize: 14, color: 'var(--text2)', fontWeight: 600, marginBottom: 6 }}>
                Loading bugs from external systems...
              </div>
              <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 6 }}>
                This may take 15–20 seconds on first load.
              </div>
              <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 16 }}>
                Bugs are cached for 5 minutes after first fetch.
              </div>
              <button className="btn btn-teal btn-sm" onClick={fetchBugs} disabled={loading}>
                {loading ? 'Loading…' : 'Retry'}
              </button>
            </div>
          )
        })()
      ) : (
        <div>
          {/* Triaged groups first */}
          {Object.values(groups).map((group) => (
            <TriagedGroup
              key={group.btId}
              group={group}
              onRetriage={handleTriage}
              retriaging={triagingId}
            />
          ))}

          {/* Expandable flat untriaged rows */}
          {flatBugs.map((bug, idx) => (
            <ExpandableBugRow
              key={`${bug.ticket_id}-${idx}`}
              bug={bug}
              onTriage={handleTriage}
              triaging={triagingId}
              navigate={navigate}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > 50 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>Previous</button>
          <span style={{ padding: '5px 12px', fontSize: 13, color: 'var(--text2)', fontFamily: 'JetBrains Mono, monospace' }}>Page {page}</span>
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((p) => p + 1)} disabled={bugs.length < 50}>Next</button>
        </div>
      )}
    </div>
  )
}
