import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { openTriageStream } from '../api/triage'
import { getCaseResult } from '../api/bugs'

/* ─── helpers ─── */
const SEV_CLS = { P0: 'sev-p0', P1: 'sev-p1', P2: 'sev-p2', P3: 'sev-p3' }
const SRC_CLS = { github: 'sb-gh', jira_apache: 'sb-jira', bugzilla: 'sb-bz', confluence: 'sb-cf' }
const SRC_LBL = { github: 'GH', jira_apache: 'JIRA', bugzilla: 'BZ', confluence: 'CF' }

function SrcBadge({ type }) {
  const cls = SRC_CLS[type] || 'sb-jira'
  const lbl = SRC_LBL[type] || (type || '?').toUpperCase().slice(0, 4)
  return <span className={`sb ${cls}`}>{lbl}</span>
}

function SevBadge({ sev }) {
  return <span className={`sev ${SEV_CLS[sev] || 'sev-unk'}`}>{sev || 'UNK'}</span>
}

const TEAM_COLORS = [
  { bg: 'var(--blue-lt)',   color: 'var(--blue)',   bd: 'var(--blue-bd)'   },
  { bg: 'var(--purple-lt)', color: 'var(--purple)', bd: 'var(--purple-bd)' },
  { bg: 'var(--teal-lt)',   color: 'var(--teal)',   bd: 'var(--teal-bd)'   },
  { bg: 'var(--amber-lt)',  color: 'var(--amber)',  bd: 'var(--amber-bd)'  },
  { bg: 'var(--orange-lt)', color: 'var(--orange)', bd: 'var(--orange-bd)' },
]

const AGENTS = [
  { id: 'cf', icon: 'CF', name: 'Context Fetch Agent',      desc: 'Fetching full ticket context + customer cases',  phase: 1 },
  { id: 'cs', icon: 'CS', name: 'Cross-System Fetch Agent', desc: 'Searching related issues across all trackers',   phase: 2 },
  { id: 'en', icon: 'EN', name: 'Enrichment Agent',         desc: 'Querying Confluence knowledge base',             phase: 2 },
  { id: 'ai', icon: 'AI', name: 'AI Synthesis Agent',       desc: 'Synthesising final triage output',               phase: 3 },
]

function agentState(id, panels) {
  const { bug_context, related_issues, linked_context, ai_summary } = panels
  if (id === 'cf') return bug_context  ? 'done' : 'running'
  if (id === 'cs') {
    if (!bug_context)  return 'wait'
    if (related_issues) return 'done'
    return 'running'
  }
  if (id === 'en') {
    if (!bug_context)   return 'wait'
    if (linked_context) return 'done'
    return 'running'
  }
  if (id === 'ai') {
    if (!related_issues || !linked_context) return 'wait'
    if (ai_summary) return 'done'
    return 'running'
  }
  return 'wait'
}

function agentStatusText(state) {
  if (state === 'done')    return '✓ Done'
  if (state === 'running') return '● Running…'
  return '○ Waiting'
}

function progress(panels) {
  const { bug_context, related_issues, linked_context, ai_summary } = panels
  if (ai_summary) return 100
  let p = 0
  if (bug_context)    p += 25
  if (related_issues) p += 25
  if (linked_context) p += 25
  return p
}

/* ═══════════════════════════════════
   LOADING STATE
═══════════════════════════════════ */
function LoadingState({ caseId, panels, elapsed }) {
  const pct = progress(panels)
  return (
    <div className="triage-load-wrap">
      <div className="triage-load-card fade-in">
        <h2>Analysing Bug</h2>
        <p>
          <span className="bt-badge" style={{ marginRight: 8 }}>{caseId}</span>
          read-only · nothing stored
        </p>
        {AGENTS.map((agent, i) => {
          const state     = agentState(agent.id, panels)
          const prevAgent = AGENTS[i - 1]
          const showPhaseLabel = i === 0 || agent.phase !== prevAgent?.phase
          return (
            <div key={agent.id}>
              {showPhaseLabel && (
                <div className="phase-lbl">
                  PHASE {agent.phase} —{' '}
                  {agent.phase === 1 ? 'SEQUENTIAL' : agent.phase === 2 ? 'PARALLEL' : 'SYNTHESIS'}
                </div>
              )}
              {agent.phase === 2 && prevAgent?.phase === 1 && (
                <div className="parallel-info">
                  ℹ Cross-System Fetch and Enrichment run in parallel
                </div>
              )}
              <div className="agent-row">
                <div className={`agent-icon ${state}`}>{state === 'done' ? '✓' : agent.icon}</div>
                <div className="agent-text">
                  <div className="agent-name">{agent.name}</div>
                  <div className="agent-desc">{agent.desc}</div>
                </div>
                <span className={`agent-status ${state}`}>{agentStatusText(state)}</span>
              </div>
            </div>
          )
        })}
        <div className="progress-wrap">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="elapsed-txt">Elapsed: {elapsed}s</div>
        </div>
      </div>
    </div>
  )
}

/* ═══════════════════════════════════
   RESULTS STATE
═══════════════════════════════════ */
function ResultsState({ caseId, panels, elapsed, onBack }) {
  const ctx      = panels.bug_context   || {}
  const related  = panels.related_issues || {}
  const linked   = panels.linked_context || {}
  const aiPanel  = panels.ai_summary    || {}

  // FIX 12: orchestrator now sends primary_ticket (was 'ticket')
  const ticket   = ctx.primary_ticket   || {}
  const synthesis = aiPanel.synthesis   || {}

  const conf       = (synthesis.confidence || 0) * 100
  const sevBlockCls = { P0: 'p0-b', P1: 'p1-b', P2: 'p2-b', P3: 'p3-b' }[synthesis.unified_severity] || 'p3-b'

  const srcType   = ticket.system_type || ticket.source
  const caseShort = `BT-${caseId.slice(-5).toUpperCase()}`

  const customerCases = ctx.customer_cases || linked.customer_cases || []

  return (
    <div className="fade-in">
      {/* Top bar */}
      <div className="result-topbar">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← Back to Bugs</button>
        <span className="bt-badge">{caseShort}</span>
        <span className="mono" style={{ fontSize: 12, color: 'var(--blue)' }}>{ticket.ticket_id || caseId}</span>
        <h2>{ticket.title || 'Triage Result'}</h2>
        <div className="result-topbar-right">
          <span style={{ fontSize: 11, color: 'var(--text3)', fontFamily: 'JetBrains Mono, monospace' }}>{elapsed}s</span>
          {srcType && <SrcBadge type={srcType} />}
        </div>
      </div>

      {/* 2×2 grid */}
      <div className="result-grid">

        {/* ── Panel 1: Bug Context ── */}
        <div className="panel teal-t">
          <div className="panel-hdr">
            <div className="panel-num pn-teal">01</div>
            <span className="panel-title">Bug Context</span>
            {srcType && <SrcBadge type={srcType} />}
          </div>
          <div className="panel-body scroll">
            {ticket.status    && <div className="meta-row"><span className="meta-k">Status</span>    <span className="meta-v">{ticket.status}</span></div>}
            {ticket.severity  && <div className="meta-row"><span className="meta-k">Severity</span>  <SevBadge sev={ticket.severity} /></div>}
            {ticket.component && <div className="meta-row"><span className="meta-k">Component</span> <span className="meta-v">{ticket.component}</span></div>}
            {ticket.assignee  && <div className="meta-row"><span className="meta-k">Assignee</span>  <span className="meta-v">{ticket.assignee}</span></div>}
            {ticket.reporter  && <div className="meta-row"><span className="meta-k">Reporter</span>  <span className="meta-v">{ticket.reporter}</span></div>}
            {ticket.created_at && (
              <div className="meta-row">
                <span className="meta-k">Created</span>
                <span className="meta-v mono" style={{ fontSize: 11 }}>{new Date(ticket.created_at).toLocaleDateString()}</span>
              </div>
            )}

            {ticket.description && (
              <>
                <div className="panel-div" />
                <p className="desc-txt">
                  {ticket.description.slice(0, 500)}
                  {ticket.description.length > 500 ? '…' : ''}
                </p>
              </>
            )}

            {customerCases.length > 0 && (
              <>
                <div className="panel-div" />
                <div className="sec-label">RELATED CUSTOMER CASES</div>
                {customerCases.map((cc, i) => (
                  <div key={i} className="cust-card">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, fontWeight: 700, color: 'var(--teal)' }}>
                        {cc.case_id}
                      </span>
                      <span style={{ fontSize: 11, fontWeight: 700, color: cc.severity === 'Critical' ? 'var(--red)' : cc.severity === 'High' ? '#D97706' : 'var(--text2)' }}>
                        {cc.severity}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--text3)' }}>{cc.customer}</span>
                    </div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)', marginBottom: 2 }}>{cc.title}</div>
                    {cc.impact && (
                      <div style={{ fontSize: 11, color: 'var(--text3)' }}>{cc.impact.slice(0, 120)}</div>
                    )}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* ── Panel 2: Related Issues ── */}
        <div className="panel blue-t">
          <div className="panel-hdr">
            <div className="panel-num pn-blue">02</div>
            <span className="panel-title">Related Issues</span>
            {(() => {
              const tickets = related.related_tickets || []
              const count   = tickets.length
              if (!count) return <span className="panel-badge pb-blue">0 found</span>
              const allWeak = tickets.every((t) => (t.similarity_score || 0) < 0.35)
              return <span className="panel-badge pb-blue">
                {allWeak ? `${count} weak match${count !== 1 ? 'es' : ''}` : `${count} found`}
              </span>
            })()}
          </div>
          <div className="panel-body scroll">
            {!related.related_tickets?.length ? (
              <p style={{ color: 'var(--text3)', fontSize: 13 }}>No related issues found above threshold.</p>
            ) : related.related_tickets.map((t, i) => {
              const score = t.similarity_score || 0
              const pct   = (score * 100).toFixed(0)
              const label = t.similarity_label || ''
              const isWeak = score < 0.35 || label === 'Possible Match'
              const isGood = !isWeak && (label === 'Good Match' || label === 'Excellent Match')
              const barColor = isWeak ? 'var(--text3)' : isGood ? 'var(--teal)' : 'var(--orange)'
              const reasonText = isWeak ? 'Weak semantic overlap — included for completeness' : t.similarity_reason
              return (
                <div key={i} className="issue-card">
                  <div className="issue-top">
                    {t.system_type && <SrcBadge type={t.system_type} />}
                    <span className="mono" style={{ fontSize: 11, color: 'var(--text2)' }}>{t.ticket_id}</span>
                    <span className="issue-name">{t.title}</span>
                    {t.severity && <SevBadge sev={t.severity} />}
                    {t.url && <a href={t.url} target="_blank" rel="noopener noreferrer" className="ext-btn">↗</a>}
                  </div>
                  <div className="sim-row">
                    <div className="sim-bar">
                      <div className="sim-fill" style={{ width: `${pct}%`, background: barColor }} />
                    </div>
                    <span className="sim-pct" style={{ color: barColor }}>{pct}% {label}</span>
                  </div>
                  {reasonText && (
                    <p className="sim-reason" style={{ color: isWeak ? 'var(--text3)' : undefined }}>{reasonText}</p>
                  )}
                  {isWeak && (
                    <p style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', margin: '2px 0 0 0' }}>
                      Low confidence match
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Panel 3: Knowledge Base / Confluence ── */}
        <div className="panel amber-t">
          <div className="panel-hdr">
            <div className="panel-num pn-amber">03</div>
            <span className="panel-title">Knowledge Base</span>
            <span className="panel-badge pb-amber">{linked.kb_articles?.length || 0} results</span>
          </div>
          <div className="panel-body scroll">
            {linked.kb_reasoning && (
              <>
                <div className="sec-label">AI ANALYSIS</div>
                <div className="root-box" style={{ borderLeftColor: 'var(--teal)' }}>
                  <p>{linked.kb_reasoning}</p>
                </div>
              </>
            )}
            {!linked.kb_articles?.length ? (
              <p style={{ color: 'var(--text3)', fontSize: 13 }}>No knowledge base articles found.</p>
            ) : linked.kb_articles.map((a, i) => {
              const scoreCls = a.score >= 5 ? 'so-score-high' : a.score >= 1 ? 'so-score-mid' : 'so-score-low'
              const relCls   = a.relevance === 'High' ? 'sev-p1' : a.relevance === 'Medium' ? 'sev-p2' : 'sev-p3'
              return (
                <div key={i} className="kb-card" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', width: '100%' }}>
                    <span className={`so-score ${scoreCls}`}>{a.score ?? 0}</span>
                    {a.is_answered && (
                      <span style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--green)', background: 'var(--green-lt)', border: '1px solid var(--green-bd)', borderRadius: 4, padding: '1px 6px' }}>
                        ✓ Answered
                      </span>
                    )}
                    <span className={`sev ${relCls}`} style={{ fontSize: 10, padding: '1px 6px' }}>{a.relevance}</span>
                    {a.space && (
                      <span style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>{a.space}</span>
                    )}
                  </div>
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ fontSize: 13, fontWeight: 600, color: 'var(--blue)', textDecoration: 'none', lineHeight: 1.3 }}
                    onMouseOver={(e) => e.target.style.textDecoration = 'underline'}
                    onMouseOut={(e) => e.target.style.textDecoration = 'none'}
                  >
                    {a.title}
                  </a>
                  {a.excerpt && (
                    <p style={{ fontSize: 11.5, color: 'var(--text3)', margin: 0, lineHeight: 1.4 }}>
                      {a.excerpt.slice(0, 160)}{a.excerpt.length > 160 ? '…' : ''}
                    </p>
                  )}
                  {a.tags?.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {a.tags.map((tag, ti) => (
                        <span key={ti} style={{ fontSize: 10, color: 'var(--text3)', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 5px', fontFamily: 'JetBrains Mono, monospace' }}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Panel 4: AI Triage Summary ── */}
        <div className="panel purple-t">
          <div className="panel-hdr">
            <div className="panel-num pn-purple">04</div>
            <span className="panel-title">AI Summary</span>
            {conf > 0 && <span className="panel-badge pb-purple">{conf.toFixed(0)}% confidence</span>}
          </div>
          <div className="panel-body scroll">
            {synthesis.used_fallback && (
              <div className="fallback-warn">⚠ Fallback analysis used — AI synthesis was unavailable</div>
            )}

            {synthesis.unified_severity && (
              <div className={`sev-block ${sevBlockCls}`}>
                <div className="sev-big">{synthesis.unified_severity}</div>
                {synthesis.severity_rationale && <div className="sev-reason">{synthesis.severity_rationale}</div>}
              </div>
            )}

            {conf > 0 && (
              <div className="conf-row">
                <span className="conf-num">{conf.toFixed(0)}%</span>
                <div className="conf-bar-wrap">
                  <div className="conf-bar">
                    <div className="conf-fill" style={{ width: `${conf}%` }} />
                  </div>
                  <div className="conf-label">AI confidence score</div>
                </div>
              </div>
            )}

            {synthesis.root_cause && (
              <>
                <div className="sec-label">Root Cause</div>
                <div className="root-box"><p>{synthesis.root_cause}</p></div>
              </>
            )}

            {synthesis.recommended_actions?.length > 0 && (
              <>
                <div className="sec-label">Recommended Actions</div>
                <ol className="rec-list">
                  {synthesis.recommended_actions.map((action, i) => (
                    <li key={i}>
                      <span className="rec-num">{String(i + 1).padStart(2, '0')}.</span>
                      {action}
                    </li>
                  ))}
                </ol>
              </>
            )}

            {synthesis.affected_teams?.length > 0 && (
              <>
                <div className="sec-label">Affected Teams</div>
                <div className="teams-wrap">
                  {synthesis.affected_teams.map((team, i) => {
                    const tc = TEAM_COLORS[i % TEAM_COLORS.length]
                    return (
                      <span key={i} className="team-tag"
                        style={{ background: tc.bg, color: tc.color, border: `1px solid ${tc.bd}` }}>
                        {team}
                      </span>
                    )
                  })}
                </div>
              </>
            )}

            {(synthesis.engineer_summary || synthesis.customer_summary) && (
              <div className="summaries-grid">
                {synthesis.engineer_summary && (
                  <div className="summary-card">
                    <div className="summary-card-lbl">Engineer Summary</div>
                    <p className="summary-card-txt">{synthesis.engineer_summary}</p>
                  </div>
                )}
                {synthesis.customer_summary && (
                  <div className="summary-card">
                    <div className="summary-card-lbl">Customer Summary</div>
                    <p className="summary-card-txt">{synthesis.customer_summary}</p>
                  </div>
                )}
              </div>
            )}

            {!synthesis.unified_severity && (
              <p style={{ color: 'var(--text3)', fontSize: 13 }}>AI analysis in progress…</p>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}

/* ═══════════════════════════════════
   MAIN TRIAGE PAGE
═══════════════════════════════════ */
export default function TriagePage() {
  const { caseId }     = useParams()
  const navigate       = useNavigate()
  const [searchParams] = useSearchParams()
  const fromHistory    = searchParams.get('from') === 'history'
  const [panels,   setPanels]   = useState({})
  const [complete, setComplete] = useState(false)
  const [elapsed,  setElapsed]  = useState(0)
  const [error,    setError]    = useState(null)
  const startTime  = useRef(Date.now())
  const cleanupRef = useRef(null)

  useEffect(() => {
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000))
    }, 1000)

    // When opened from history, reconstruct panels from cached context
    if (fromHistory) {
      getCaseResult(caseId)
        .then((cached) => {
          if (cached) {
            const ctx = cached.context || {}
            setPanels({
              bug_context: {
                primary_ticket: ctx.primary_ticket || null,
                keywords:       ctx.keywords       || [],
                components:     ctx.components     || [],
                customer_cases: ctx.customer_cases || [],
              },
              related_issues: {
                related_tickets: ctx.related_tickets || [],
                sources_queried: ctx.sources_queried || [],
              },
              linked_context: {
                kb_articles:  ctx.kb_articles  || [],
                kb_reasoning: ctx.kb_reasoning || '',
                customer_cases: ctx.customer_cases || [],
              },
              ai_summary: {
                synthesis: ctx.synthesis || {},
              },
            })
            setComplete(true)
            clearInterval(timer)
          } else {
            setError('Result expired. Please re-triage.')
            clearInterval(timer)
          }
        })
        .catch(() => {
          setError('Result expired. Please re-triage.')
          clearInterval(timer)
        })
      return () => { clearInterval(timer) }
    }

    // Live pipeline — open WebSocket and receive panels as they arrive
    cleanupRef.current = openTriageStream(
      caseId,
      (panelName, data) => {
        setPanels((prev) => ({ ...prev, [panelName]: data }))
      },
      () => { setComplete(true); clearInterval(timer) },
      (msg) => { setError(msg || 'WebSocket connection error.') }
    )

    return () => {
      clearInterval(timer)
      if (cleanupRef.current) cleanupRef.current()
    }
  }, [caseId])

  const handleBack = () => navigate('/bugs')

  return (
    <div>
      {error && (
        <div style={{
          padding: '9px 14px', marginBottom: 14,
          background: 'var(--red-lt)', border: '1px solid var(--red-bd)',
          borderRadius: 7, color: 'var(--red)', fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {complete ? (
        <ResultsState caseId={caseId} panels={panels} elapsed={elapsed} onBack={handleBack} />
      ) : (
        <LoadingState caseId={caseId} panels={panels} elapsed={elapsed} />
      )}
    </div>
  )
}
