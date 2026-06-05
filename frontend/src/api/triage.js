import client from './client'

export const startTriage = (bugId, sourceId = "", forceRefresh = false) =>
  client.post('/triage', { bug_id: bugId, source_id: sourceId, force_refresh: forceRefresh }).then(r => r.data)

export const openTriageStream = (caseId, onPanel, onComplete, onError) => {
  const token = localStorage.getItem('hpe_token') || ''
  const wsUrl = `ws://localhost:8000/triage/${caseId}/stream?token=${token}`

  let ws = null
  let reconnectAttempts = 0
  const seenPanels = new Set()
  let closed = false
  let done = false

  const applyPanel = (panelName, data) => {
    if (!panelName) return
    seenPanels.add(panelName)
    onPanel(panelName, data)
  }

  const hydrateFromCase = async () => {
    try {
      const cached = await client.get(`/cases/${caseId}`).then((r) => r.data)
      for (const event of cached.panels || []) {
        if (event.panel) applyPanel(event.panel, event.data)
        if (event.type === 'pipeline_done' || event.type === 'pipeline_complete') {
          done = true
          closed = true
          onComplete(event)
        }
      }
      const ctx = cached.context || {}
      if (ctx.primary_ticket || ctx.bug_context) {
        applyPanel('bug_context', {
          bug_context: ctx.bug_context || null,
          primary_ticket: ctx.primary_ticket || null,
          components: ctx.components || [],
          customer_cases: ctx.customer_cases || [],
          customer_signals: ctx.customer_signals || [],
          source_references: ctx.source_references || [],
        })
      }
      if (ctx.related_tickets) {
        applyPanel('related_issues', {
          related_tickets: ctx.related_tickets || [],
          sources_queried: ctx.sources_queried || [],
        })
      }
      if (ctx.kb_articles || ctx.kb_reasoning) {
        applyPanel('linked_context', {
          kb_articles: ctx.kb_articles || [],
          kb_reasoning: ctx.kb_reasoning || '',
          customer_cases: ctx.customer_cases || [],
        })
      }
      if (ctx.synthesis) {
        applyPanel('ai_summary', {
          synthesis: ctx.synthesis || {},
          errors: ctx.errors || {},
        })
      }
      if (ctx.pipeline_done && !done) {
        done = true
        closed = true
        onComplete(ctx.pipeline_done)
      }
    } catch (_e) {
      // Case state may not exist yet; the WebSocket remains the live path.
    }
  }

  const connect = () => {
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log(`[WS] Connected for case ${caseId}`)
      reconnectAttempts = 0
      hydrateFromCase()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'heartbeat') return
        if (msg.panel) {
          applyPanel(msg.panel, msg.data)
        } else if (msg.type === 'pipeline_done' || msg.type === 'pipeline_complete') {
          done = true
          closed = true
          onComplete(msg)
          ws.close()
        } else if (msg.type === 'error') {
          onError(msg.message)
        }
      } catch (e) {
        console.error('[WS] Parse error:', e)
      }
    }

    ws.onerror = (e) => {
      console.error('[WS] Error:', e)
    }

    ws.onclose = (e) => {
      console.log(`[WS] Closed: code=${e.code} panels=${seenPanels.size}`)
      if (closed) return

      hydrateFromCase()
      reconnectAttempts++
      const delay = Math.min(1000 * reconnectAttempts, 8000)
      console.log(`[WS] Reconnecting attempt ${reconnectAttempts}`)
      setTimeout(() => {
        if (!closed && !done) connect()
      }, delay)
    }
  }

  connect()

  const fallbackTimer = setInterval(() => {
    if (!closed && !done) hydrateFromCase()
  }, 5000)

  return () => {
    closed = true
    clearInterval(fallbackTimer)
    if (ws && ws.readyState === WebSocket.OPEN) ws.close()
  }
}
