import client from './client'

export const startTriage = (bugId) =>
  client.post('/triage', { bug_id: bugId }).then(r => r.data)

export const openTriageStream = (caseId, onPanel, onComplete, onError) => {
  const token = localStorage.getItem('hpe_token') || ''
  const wsUrl = `ws://localhost:8000/triage/${caseId}/stream?token=${token}`
  const ws = new WebSocket(wsUrl)

  let panelsReceived = 0
  const EXPECTED_PANELS = 4

  ws.onopen = () => {
    console.log('WebSocket connected for case', caseId)
  }

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      console.log('WS message received:', msg.type || msg.panel, msg)

      if (msg.panel) {
        panelsReceived++
        onPanel(msg.panel, msg.data)
      } else if (msg.type === 'pipeline_complete') {
        onComplete(msg)
        ws.close()
      } else if (msg.type === 'error') {
        onError(msg.message)
      }
    } catch (e) {
      console.error('WS parse error:', e)
    }
  }

  ws.onerror = (e) => {
    console.error('WebSocket error:', e)
    onError('WebSocket connection error')
  }

  ws.onclose = (e) => {
    console.log('WebSocket closed', e.code, e.reason)
    if (panelsReceived > 0 && panelsReceived < EXPECTED_PANELS) {
      onError('Connection closed before all panels arrived')
    }
  }

  const timeout = setTimeout(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.close()
      onError('Triage timed out after 60 seconds')
    }
  }, 60000)

  return () => {
    clearTimeout(timeout)
    if (ws.readyState === WebSocket.OPEN) ws.close()
  }
}
