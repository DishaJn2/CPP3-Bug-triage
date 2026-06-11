import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBugs, getBugStatus, refreshBugCache, getMetrics } from '../api/bugs'
import { startTriage } from '../api/triage'
import { useBugListCache } from '../context/BugListCacheContext'

const toPercent = (score) => {
  if (score == null) return 0
  if (score > 1) return Math.min(Math.round(score), 100)
  return Math.min(Math.round(score * 100), 100)
}

const SRC_CLS = { github: 'sb-gh', jira: 'sb-jira', jira_apache: 'sb-jira', jira_cloud: 'sb-jira', bugzilla: 'sb-bz', confluence: 'sb-cf', customer_portal: 'sb-jira', support_kb: 'sb-cf' }
const SRC_LBL = { github: 'GH', jira: 'JIRA', jira_apache: 'JIRA', jira_cloud: 'JIRA', bugzilla: 'BZ', confluence: 'CF', customer_portal: 'CP', support_kb: 'KB' }
const SEV_CLS = { P0: 'sev-p0', P1: 'sev-p1', P2: 'sev-p2', P3: 'sev-p3' }
const SEVERITY_ORDER = ['P0', 'P1', 'P2', 'P3', 'Unknown']
const ALL_SOURCES = ['All Sources', 'github', 'jira_apache', 'bugzilla']
const BUGLIST_CACHE_MAX_AGE_MS = 120000

function SevBadge({ sev }) {
  return <span className={`sev ${SEV_CLS[sev] || 'sev-unk'}`}>{sev || 'UNK'}</span>
}

function SrcBadge({ type }) {
  return <span className={`sb ${SRC_CLS[type] || 'sb-jira'}`}>{SRC_LBL[type] || (type || '?').toUpperCase().slice(0, 4)}</span>
}

function getSourceType(item = {}) {
  return (item.system_type || item.source || item.source_id || '').toLowerCase()
}

function getGroupRoot(group = {}) {
  return group.root || group.primary || group.primary_bug || group.children?.[0] || null
}

function getGroupChildren(group = {}) {
  if (group.root || group.primary || group.primary_bug) return group.children || []
  return (group.children || []).slice(1)
}

function matchesPill(item, pill) {
  if (pill === 'All') return true
  if (pill === 'Untriaged') return !item?.is_triaged
  if (pill === 'Triaged') return !!item?.is_triaged
  if (pill === 'Critical') return item?.severity === 'P0' || item?.severity === 'P1'
  return true
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch { return '—' }
}

/* ─── Status panel (SD7 / SD8 / SD9) shown when expanding an untriaged row ─── */
function formatChange(change) {
  if (!change) return ''
  if (typeof change === 'string') return change
  const field = change.field || 'field'
  const from = change.from || 'empty'
  const to = change.to || 'empty'
  return `${field}: ${from} -> ${to}`
}

function PreviousTriageResult({ status, triage = {} }) {
  const severity = status?.last_ai_severity || status?.last_severity || triage.severity || 'Unknown'
  const confidence = status?.last_confidence ?? triage.confidence
  const triagedAt = status?.last_triaged_at || triage.triaged_at
  const rootCause = status?.root_cause || triage.root_cause || ''
  const confPct = confidence != null ? toPercent(confidence) : null

  return (
    <div style={{ fontSize: 12, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 700, color: 'var(--text)' }}>Previous triage result</span>
        <SevBadge sev={severity} />
        {confPct != null && <span className="match-badge match-h">{confPct}%</span>}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace' }}>
        Last triaged: {fmtDate(triagedAt)}
      </div>
      {rootCause && (
        <div><strong>Root cause:</strong> {rootCause}</div>
      )}
    </div>
  )
}

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
        padding: '12px 24px', display: 'flex', alignItems: 'center',
      }}>
        <button className="btn btn-teal btn-sm" onClick={() => onTriage(bugId)} disabled={triaging === bugId}>
          {triaging === bugId ? '…' : 'Triage'}
        </button>
      </div>
    )
  }

  if (status.needs_retriage == null) {
    return (
      <div style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)', padding: '12px 24px' }}>
        <div style={{
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 7, padding: '9px 12px', marginBottom: 10,
          fontSize: 12, color: 'var(--text3)',
        }}>
          Source unavailable — showing last known result
        </div>
        <PreviousTriageResult status={status} />
      </div>
    )
  }

  // SD7 — changes found
  if (status.needs_retriage === true) {
    return (
      <div style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)', padding: '12px 24px' }}>
        <div style={{
          background: 'var(--orange-lt)', border: '1px solid var(--orange-bd)',
          borderRadius: 7, padding: '9px 12px', marginBottom: 10, fontSize: 12, color: 'var(--orange)',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>⚠ Changes detected since last triage:</div>
          {(status.changes || []).length > 0 ? (
            status.changes.map((c, i) => <div key={i} style={{ marginLeft: 8 }}>• {formatChange(c)}</div>)
          ) : (
            <div style={{ marginLeft: 8 }}>Ticket metadata changed since last triage.</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <button className="btn btn-teal btn-sm" onClick={() => onTriage(bugId)} disabled={triaging === bugId}>
            {triaging === bugId ? '…' : 'Run Fresh Triage'}
          </button>
        </div>
        <PreviousTriageResult status={status} />
      </div>
    )
  }

  // SD8 — no changes
  return (
    <div style={{ background: 'var(--bg)', borderTop: '1px solid var(--border)', padding: '12px 24px' }}>
      <PreviousTriageResult status={status} />
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button className="btn btn-outline btn-sm" onClick={() => onTriage(bugId, true)} disabled={triaging === bugId}>
          {triaging === bugId ? '…' : 'Run Fresh Triage'}
        </button>
      </div>
    </div>
  )
}

/* ─── Expandable flat row for UNTRIAGED bugs ─── */
function StatusBadge({ status, loading, error }) {
  if (loading) {
    return <span className="bug-status-pill">Checking</span>
  }
  if (error) {
    return <span className="bug-status-pill">Unknown</span>
  }
  if (status?.needs_retriage) {
    return <span className="bug-status-pill" style={{ color: 'var(--orange)', borderColor: 'var(--orange-bd)', background: 'var(--orange-lt)' }}>Changes detected</span>
  }
  if (status && !status.is_new) {
    return <span className="current-badge">✓ Current</span>
  }
  return <span className="bug-status-pill">Unknown</span>
}

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
        setStatus({
          ...s,
          changes: (s.changes || []).map(formatChange),
        })
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
        <button onClick={handleExpand} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          fontSize: 10, color: 'var(--text3)', padding: '2px 4px', flexShrink: 0,
        }}>
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
          onClick={() => onTriage(bug)}
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
          onTriage={() => onTriage(bug)}
          onView={handleView}
          triaging={triaging}
        />
      )}
    </div>
  )
}

function GroupTreeRow({ group, onTriage, triaging }) {
  const root = getGroupRoot(group)
  const children = getGroupChildren(group)
  const groupId = group.group_id || root?.ticket_id || group.id || 'group'
  const [open, setOpen] = useState(false)

  if (!root) return null

  const sourceType = getSourceType(root)
  const rootUrl = root.url || ''

  return (
    <div className="tree-group" style={{ border: '1px solid var(--border)', background: 'var(--white)' }}>
      <div
        className="tree-root"
        style={{ border: 'none', borderRadius: 0 }}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`expand-arrow${open ? ' open' : ''}`}>▶</span>
        <span className="bt-badge">Root / Primary</span>
        <SrcBadge type={sourceType} />
        {rootUrl ? (
          <a
            className="raw-id"
            href={rootUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            {root.ticket_id}
          </a>
        ) : (
          <span className="raw-id">{root.ticket_id}</span>
        )}
        <span className="bug-flat-title">{root.title || group.title || 'Grouped issue'}</span>
        <SevBadge sev={root.severity || group.priority} />
        <span className="bug-status-pill">{root.status || group.status || 'open'}</span>
        <span className="match-badge match-m">{children.length} Related</span>
        <button
          className="btn btn-teal btn-sm"
          onClick={(e) => { e.stopPropagation(); onTriage(root) }}
          disabled={triaging === root.ticket_id}
        >
          {triaging === root.ticket_id ? '...' : '▶ Triage'}
        </button>
      </div>

      {open && (
        <div className="tree-children">
          {children.length === 0 ? (
            <div className="tree-child">
              <span className="tree-connector">└─</span>
              <span style={{ fontSize: 12, color: 'var(--text3)' }}>No related child rows in this group yet.</span>
            </div>
          ) : children.map((child, idx) => {
            const childSource = getSourceType(child)
            const childUrl = child.url || ''
            return (
              <div key={`${groupId}-${child.ticket_id || idx}`} className="tree-child">
                <span className="tree-connector">└─</span>
                <span className="match-badge match-l">Related</span>
                <SrcBadge type={childSource} />
                {childUrl ? (
                  <a
                    className="raw-id"
                    href={childUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {child.ticket_id}
                  </a>
                ) : (
                  <span className="raw-id">{child.ticket_id}</span>
                )}
                <span className="child-title">{child.title || 'Related issue'}</span>
                <SevBadge sev={child.severity} />
                <span className="bug-status-pill">{child.status || 'open'}</span>
                {childUrl && (
                  <a className="ext-btn" href={childUrl} target="_blank" rel="noopener noreferrer">
                    ↗
                  </a>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* ─── Tree row for TRIAGED bugs — shows AI analysis as child ─── */
function TriagedBugRow({ bug, onRetriage, retriaging, navigate }) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState(false)
  const triage = bug.triage_info || {}
  const confPct = triage.confidence != null ? toPercent(triage.confidence) : null
  const triagedAt = fmtDate(triage.triaged_at)
  const caseIdShort = triage.case_id ? `BT-${triage.case_id.slice(0, 6).toUpperCase()}` : 'BT-?'
  const systems = triage.systems_queried || []
  const statusCaseId = status?.case_id || triage.case_id
  const statusConfPct = status?.last_confidence != null ? toPercent(status.last_confidence) : confPct
  const statusTriagedAt = fmtDate(status?.last_triaged_at || triage.triaged_at)

  const fetchStatus = async () => {
    setStatusLoading(true)
    setStatusError(false)
    try {
      const s = await getBugStatus(bug.ticket_id)
      setStatus({
        ...s,
        changes: (s.changes || []).map(formatChange),
      })
    } catch {
      setStatus(null)
      setStatusError(true)
    } finally {
      setStatusLoading(false)
    }
  }

  const handleToggle = async () => {
    const next = !open
    setOpen(next)
    if (next && !status && !statusLoading) {
      await fetchStatus()
    }
  }

  const handleView = (e) => {
    e.stopPropagation()
    if (statusCaseId) navigate(`/triage/${statusCaseId}?from=history`)
  }

  return (
    <div style={{
      background: 'var(--white)', borderRadius: 8, marginBottom: 5, overflow: 'hidden',
      border: '1px solid var(--border)', borderLeft: '4px solid var(--teal)',
    }}>
      {/* Root row */}
      <div
        className="bug-flat"
        style={{ borderRadius: 0, border: 'none', marginBottom: 0, cursor: 'pointer' }}
        onClick={handleToggle}
      >
        <span style={{
          fontSize: 10, color: 'var(--text3)', padding: '2px 4px', flexShrink: 0,
          transform: open ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.15s',
        }}>▶</span>
        <span className="bt-badge">{caseIdShort}</span>
        <SrcBadge type={bug.system_type} />
        <span className="raw-id">{bug.ticket_id}</span>
        <span className="bug-flat-title">{bug.title}</span>
        <SevBadge sev={triage.severity || bug.severity} />
        {confPct != null && (
          <span className="match-badge match-h">{confPct}%</span>
        )}
        <StatusBadge status={status} loading={statusLoading} error={statusError} />
        <span className="bug-flat-time">{triagedAt}</span>
        {statusCaseId && (
          <button
            className="btn btn-outline btn-sm"
            onClick={handleView}
          >
            View Previous Results
          </button>
        )}
      </div>

      {/* Expanded children — AI analysis */}
      {open && (
        <div style={{ borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
          {statusLoading ? (
            <div style={{ padding: '12px 24px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div className="skeleton-pulse" style={{ width: 180, height: 13, borderRadius: 3 }} />
              <div className="skeleton-pulse" style={{ width: 120, height: 13, borderRadius: 3 }} />
            </div>
          ) : statusError || status?.needs_retriage == null ? (
            <div style={{ padding: '12px 24px' }}>
              <div style={{
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 7, padding: '9px 12px', marginBottom: 10,
                fontSize: 12, color: 'var(--text3)',
              }}>
                Source unavailable — showing last known result
              </div>
              <PreviousTriageResult status={status} triage={triage} />
            </div>
          ) : status.needs_retriage === true ? (
            <div style={{ padding: '12px 24px' }}>
              <div style={{
                background: 'var(--orange-lt)', border: '1px solid var(--orange-bd)',
                borderRadius: 7, padding: '9px 12px', marginBottom: 10, fontSize: 12, color: 'var(--orange)',
              }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>⚠ Changes detected since last triage</div>
                {(status.changes || []).length > 0 ? (
                  status.changes.map((c, i) => <div key={i} style={{ marginLeft: 8 }}>• {formatChange(c)}</div>)
                ) : (
                  <div style={{ marginLeft: 8 }}>Ticket metadata changed since last triage.</div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                <button
                  className="btn btn-teal btn-sm"
                  onClick={(e) => { e.stopPropagation(); onRetriage(bug, true) }}
                  disabled={retriaging === bug.ticket_id}
                >
                  {retriaging === bug.ticket_id ? '…' : 'Run Fresh Triage'}
                </button>
              </div>
              <PreviousTriageResult status={status} triage={triage} />
            </div>
          ) : status ? (
            <div style={{ padding: '12px 24px' }}>
              <PreviousTriageResult status={status} triage={triage} />
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={(e) => { e.stopPropagation(); onRetriage(bug, true) }}
                  disabled={retriaging === bug.ticket_id}
                >
                  {retriaging === bug.ticket_id ? '…' : 'Run Fresh Triage'}
                </button>
              </div>
            </div>
          ) : null}
          <div style={{
            marginLeft: 24, paddingLeft: 16, paddingTop: 10, paddingBottom: 10,
            borderLeft: '2px solid var(--border)', position: 'relative',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
              <span style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace' }}>└─</span>
              <span style={{ fontSize: 12, color: 'var(--teal)', fontWeight: 700 }}>AI Analysis</span>
              {triage.severity && <SevBadge sev={triage.severity} />}
              {triage.case_id && (
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ fontSize: 11 }}
                  onClick={(e) => { e.stopPropagation(); navigate(`/triage/${triage.case_id}?from=history`) }}
                >
                  View Results ↗
                </button>
              )}
            </div>
            {systems.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: 'var(--text3)', marginLeft: 24 }}>
                <span style={{ fontFamily: 'JetBrains Mono, monospace' }}>└─</span>
                <span>Systems checked: <strong>{systems.join(', ')}</strong></span>
                {confPct != null && (
                  <span style={{ color: 'var(--teal)', marginLeft: 8 }}>Confidence: {confPct}%</span>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export const clearBugsCache = () => {
  for (const k in bugsCache) {
    delete bugsCache[k]
  }
}

const bugsCache = {};

export default function BugListPage() {
  const { cache: bugListCache, updateCache: updateBugListCache } = useBugListCache()
  const navigate      = useNavigate()
  const intervalRef   = useRef(null)
  const pollCountRef  = useRef(0)
  const [bugs,          setBugs]          = useState([])
  const [groups,        setGroups]        = useState([])
  const [flatRows,      setFlatRows]      = useState([])
  const [total,         setTotal]         = useState(0)
  const [page,          setPage]          = useState(1)
  const [pageInput,     setPageInput]     = useState('')
  const [loading,       setLoading]       = useState(true)
  const [searchInput,   setSearchInput]   = useState('')
  const [search,        setSearch]        = useState('')
  const [severity,      setSeverity]      = useState('')
  const [source,        setSource]        = useState('')
  const [status,        setStatus]        = useState('')
  const [activePill,    setActivePill]    = useState('All')
  const [triagingId,    setTriagingId]    = useState(null)
  const [lastSynced,    setLastSynced]    = useState(() => bugListCache.lastSynced ? new Date(bugListCache.lastSynced) : null)
  const [directBugId,   setDirectBugId]  = useState('')
  const [refreshing,    setRefreshing]    = useState(false)
  const [sourcesOnline, setSourcesOnline] = useState(() => bugListCache.sourcesOnline || 0)
  const [isPartial,     setIsPartial]     = useState(() => bugListCache.isPartial || false)
  const [cacheStatus,   setCacheStatus]   = useState(() => bugListCache.cacheStatus || null)
  const [metrics,       setMetrics]       = useState(null)

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search !== searchInput) {
        setSearch(searchInput)
        setPage(1)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [searchInput, search])

  useEffect(() => {
    updateBugListCache({
      page,
      searchTerm: search,
      filters: {
        severity,
        source,
        status,
        activePill,
      },
    })
  }, [page, search, severity, source, status, activePill, updateBugListCache])

  const fetchBugs = useCallback(async (silent = false) => {
    const key = JSON.stringify({ page, page_size: 10, severity, source, status, search })
    const now = Date.now()
    const cached = bugsCache[key]
    const isExpired = !cached || (now - cached.timestamp) >= 120000

    if (cached) {
      const { data } = cached
      const nextGroups = data.groups || []
      const allBugs = data.bugs || [
        ...(data.ungrouped || []),
        ...nextGroups.flatMap((g) => g.children || []),
      ]
      const nextFlatRows = nextGroups.length > 0 ? (data.ungrouped || []) : allBugs
      setBugs(allBugs)
      setGroups(nextGroups)
      setFlatRows(nextFlatRows)
      setTotal(data.total || 0)
      setSourcesOnline(data.sources_online || 0)
      setIsPartial(data.partial || false)
      setLastSynced(new Date(cached.timestamp))
      setCacheStatus(data.cache_status || 'hit')
    }

    if (!isExpired) return

    if (!silent && !cached) {
      setLoading(true)
      pollCountRef.current = 0
    }
    try {
      const data = await getBugs({ page, page_size: 10, severity, source: source || undefined, status, search })
      bugsCache[key] = { data, timestamp: Date.now() }
      const nextGroups = data.groups || []
      const allBugs = data.bugs || [
        ...(data.ungrouped || []),
        ...nextGroups.flatMap((g) => g.children || []),
      ]
      const nextFlatRows = nextGroups.length > 0 ? (data.ungrouped || []) : allBugs
      const fetchedAt = Date.now()
      const syncedAt = new Date(fetchedAt)
      setBugs(allBugs)
      setGroups(nextGroups)
      setFlatRows(nextFlatRows)
      setTotal(data.total || 0)
      setSourcesOnline(data.sources_online || 0)
      setIsPartial(data.partial || false)
      setLastSynced(syncedAt)
      setCacheStatus(data.cache_status || 'hit')
      updateBugListCache({
        bugs: allBugs,
        groups: nextGroups,
        flatRows: nextFlatRows,
        total: data.total || 0,
        page,
        searchTerm: search,
        filters: {
          severity,
          source,
          status,
          activePill,
        },
        sourcesOnline: data.sources_online || 0,
        isPartial: data.partial || false,
        cacheStatus: data.cache_status || 'hit',
        lastFetched: fetchedAt,
        lastSynced: syncedAt.toISOString(),
      })
    } catch (e) {
      console.error('Failed to fetch bugs', e)
    } finally {
      if (!silent && !cached) setLoading(false)
    }
  }, [page, severity, source, status, search, activePill, bugs.length, updateBugListCache])

  useEffect(() => {
    const cacheMatches =
      bugListCache.page === page &&
      (bugListCache.searchTerm || '') === search &&
      (bugListCache.filters?.severity || '') === severity &&
      (bugListCache.filters?.source || '') === source &&
      (bugListCache.filters?.status || 'open') === status
    const hasCachedRows = cacheMatches && ((bugListCache.bugs || []).length > 0 || (bugListCache.groups || []).length > 0)
    const cacheAge = Date.now() - (bugListCache.lastFetched || 0)
    const cacheIsFresh = hasCachedRows && cacheAge < BUGLIST_CACHE_MAX_AGE_MS

    if (cacheIsFresh) {
      setLoading(false)
    } else if (hasCachedRows) {
      setLoading(false)
      fetchBugs(true)
    } else {
      fetchBugs()
    }

    intervalRef.current = setInterval(() => fetchBugs(true), 120000)
    return () => clearInterval(intervalRef.current)
  }, [fetchBugs, page, search, severity, source, status])

  // Poll every 1 s on cold start until data arrives (max 3 polls, then stop)
  useEffect(() => {
    if (cacheStatus !== 'cold') return
    if (pollCountRef.current >= 3) return  // hard stop at 3

    const timer = setTimeout(() => {
      pollCountRef.current += 1
      fetchBugs(true)  // silent fetch
    }, 1000)

    return () => clearTimeout(timer)
  }, [cacheStatus, fetchBugs])

  // Fetch metrics for dashboard strip
  useEffect(() => {
    getMetrics().then(setMetrics).catch(console.error)
  }, [])

  const handleTriage = async (bugOrId, forceRefresh = false) => {
    // Accept either a full bug object { ticket_id, source_id } or a plain string (direct triage bar)
    const bugId    = typeof bugOrId === 'string' ? bugOrId : bugOrId.ticket_id
    const sourceId = typeof bugOrId === 'string' ? '' : (bugOrId.source_id || '')
    setTriagingId(bugId)
    try {
      const data = await startTriage(bugId, sourceId, forceRefresh)
      navigate(`/triage/${data.case_id}`)
    } catch (e) {
      alert('Failed to start triage: ' + (e.response?.data?.detail || e.message))
    } finally {
      setTriagingId(null)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refreshBugCache() } catch { /* ignore */ }
    
    // Invalidate caches
    for (const k in bugsCache) delete bugsCache[k]

    await new Promise((r) => setTimeout(r, 3000))
    await fetchBugs()
    setRefreshing(false)
  }

  const syncMinsAgo = lastSynced ? Math.round((Date.now() - lastSynced) / 60000) : null

  const visibleGroups = groups.filter((group) => {
    const root = getGroupRoot(group)
    return matchesPill(root || {}, activePill)
  })
  const visibleFlatRows = flatRows.filter((b) => matchesPill(b, activePill))

  const triaged  = bugs.filter((b) => b.is_triaged).length
  const awaiting = bugs.length - triaged
  const start    = (page - 1) * 50 + 1
  const end      = Math.min((page - 1) * 50 + bugs.length, total)

  const triagedBugs   = visibleFlatRows.filter((b) => b.is_triaged)
  const untriagedBugs = visibleFlatRows.filter((b) => !b.is_triaged)
  const hasVisibleRows = visibleGroups.length > 0 || visibleFlatRows.length > 0

  return (
    <div>
      {/* Dashboard strip */}
      {metrics && (
        <div style={{
          display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap',
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 8, padding: '8px 14px', alignItems: 'center', fontSize: 12, fontWeight: 500,
        }}>
          <span style={{ color: 'var(--red)', fontWeight: 700 }}>🔴 P0: {metrics.live_p0_count ?? 0}</span>
          <span style={{ color: 'var(--text3)' }}>·</span>
          <span style={{ color: '#D97706', fontWeight: 700 }}>🟠 P1: {metrics.live_p1_count ?? 0}</span>
          <span style={{ color: 'var(--text3)' }}>·</span>
          <span style={{ color: 'var(--green)' }}>✅ Triaged Today: {metrics.triaged_today ?? 0}</span>
          <span style={{ color: 'var(--text3)' }}>·</span>
          <span style={{ color: '#D97706' }}>⏳ Needs Triage: {metrics.needs_triage ?? 0}</span>
          <span style={{ color: 'var(--text3)' }}>·</span>
          <span style={{ color: 'var(--red)' }}>Failed: {metrics.failed_triages ?? 0}</span>
          <span style={{ color: 'var(--text3)' }}>Â·</span>
          <span style={{ color: 'var(--teal)', fontWeight: 700 }}>
            🟢 {metrics.sources_online ?? 0}/{metrics.sources_total ?? 0} Systems Online
          </span>
        </div>
      )}

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

        <select
          className="form-select filter-select"
          style={{ width: 'auto' }}
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1) }}
        >
          <option value="">All Statuses</option>
          <option value="open">Open</option>
          <option value="in progress">In Progress</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>

        <div className="filter-pills">
          {['All', 'Untriaged', 'Triaged', 'Critical'].map((p) => (
            <button
              key={p}
              className={`pill${activePill === p ? ' active' : ''}`}
              onClick={() => setActivePill(p)}
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
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= AI triage session</span>
          <span className="current-badge">✓ Current</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= triaged, no changes</span>
          <span className="match-badge match-h">90%</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= AI confidence</span>
          <span className="raw-id">DISK-779</span>
          <span style={{ fontSize: 11, color: 'var(--text3)' }}>= untriaged bug ID</span>
        </div>
      </div>

      {/* Stats line */}
      {!loading && (
        <div className="stats-line">
          Showing {start}–{end} of {total} bugs · {triaged} triaged · {awaiting} untriaged · Sort: Severity
        </div>
      )}

      {/* Partial results banner */}
      {!loading && isPartial && bugs.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
          background: 'var(--orange-lt)', border: '1px solid var(--orange-bd)',
          borderRadius: 7, padding: '8px 14px', fontSize: 12, color: 'var(--orange)',
        }}>
          <span style={{ flex: 1 }}>⚠ Showing partial results — some sources are still loading</span>
          <button className="btn btn-ghost btn-sm" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      )}

      {/* Non-blocking cold-start banner (shown while background fetch runs) */}
      {!loading && cacheStatus === 'cold' && bugs.length === 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10,
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 7, padding: '10px 14px', fontSize: 13, color: 'var(--text2)',
        }}>
          <span style={{
            display: 'inline-block', width: 14, height: 14, borderRadius: '50%',
            border: '2px solid var(--teal)', borderTopColor: 'transparent',
            animation: 'spin 0.8s linear infinite', flexShrink: 0,
          }} />
          <span>Fetching live data… (first load)</span>
        </div>
      )}

      {/* Bug rows */}
      {loading && bugs.length === 0 ? (
        <div>
          {[...Array(5)].map((_, i) => (
            <div key={i} style={{
              height: '64px',
              background: 'var(--color-background-secondary)',
              borderRadius: '8px',
              marginBottom: '8px',
              opacity: 1 - (i * 0.15),
              animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          ))}
        </div>
      ) : !hasVisibleRows ? (
        (() => {
          const hasFilters = !!(search || severity || source || activePill !== 'All')
          if (hasFilters) {
            return (
              <div className="card" style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)', fontSize: 13 }}>
                <div style={{ marginBottom: 12 }}>No bugs match the current filter.</div>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setSearchInput(''); setSearch(''); setSeverity(''); setSource(''); setActivePill('All'); setPage(1)
                  }}
                >
                  Clear filters
                </button>
              </div>
            )
          }
          if (cacheStatus === 'cold') return null  // banner above is shown instead
          return (
            <div className="card" style={{ textAlign: 'center', padding: '40px', color: 'var(--text3)', fontSize: 13 }}>
              <div style={{ marginBottom: 12 }}>No bugs found. Try refreshing.</div>
              <button className="btn btn-ghost btn-sm" onClick={() => fetchBugs()}>Retry</button>
            </div>
          )
        })()
      ) : (
        <div>
          {visibleGroups.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              {visibleGroups.map((group, idx) => (
                <GroupTreeRow
                  key={group.group_id || getGroupRoot(group)?.ticket_id || `group-${idx}`}
                  group={group}
                  onTriage={handleTriage}
                  triaging={triagingId}
                />
              ))}
            </div>
          )}

          {/* Untriaged bugs first — flat expandable rows */}
          {untriagedBugs.map((bug, idx) => (
            <ExpandableBugRow
              key={`${bug.ticket_id}-${idx}`}
              bug={bug}
              onTriage={handleTriage}
              triaging={triagingId}
              navigate={navigate}
            />
          ))}

          {/* Triaged bugs — tree rows with AI analysis children */}
          {triagedBugs.map((bug, idx) => (
            <TriagedBugRow
              key={`triaged-${bug.ticket_id}-${idx}`}
              bug={bug}
              onRetriage={(b, fr) => handleTriage(b, fr)}
              retriaging={triagingId}
              navigate={navigate}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > 10 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 12, marginTop: 20 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>Previous</button>
          
          {(() => {
            const totalPages = Math.ceil(total / 10)
            const pages = []
            
            for (let i = 1; i <= totalPages; i++) {
              if (i === 1 || i === totalPages || (i >= page - 2 && i <= page + 2)) {
                pages.push(
                  <button 
                    key={i} 
                    className={`btn btn-sm ${page === i ? 'btn-teal' : 'btn-ghost'}`}
                    onClick={() => setPage(i)}
                    style={{ minWidth: 32, padding: '4px 8px' }}
                  >
                    {i}
                  </button>
                )
              } else if (i === page - 3 || i === page + 3) {
                pages.push(<span key={i} style={{ color: 'var(--text3)' }}>...</span>)
              }
            }
            return <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>{pages}</div>
          })()}
          
          <button className="btn btn-ghost btn-sm" onClick={() => setPage((p) => Math.min(Math.ceil(total / 10), p + 1))} disabled={page >= Math.ceil(total / 10)}>Next</button>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 16, borderLeft: '1px solid var(--border)', paddingLeft: 16 }}>
            <span style={{ fontSize: 13, color: 'var(--text2)' }}>Go to:</span>
            <input 
              type="number" 
              className="form-input" 
              style={{ width: 60, padding: '4px 8px', fontSize: 13 }}
              value={pageInput}
              onChange={(e) => setPageInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const p = parseInt(pageInput, 10)
                  if (p >= 1 && p <= Math.ceil(total / 10)) {
                    setPage(p)
                    setPageInput('')
                  }
                }
              }}
              min={1}
              max={Math.ceil(total / 10)}
            />
          </div>
        </div>
      )}
    </div>
  )
}
