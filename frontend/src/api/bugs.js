import client from './client'

export const getBugs = (params = {}) =>
  client.get('/bugs', { params, timeout: 20000 }).then((r) => r.data)

export const getBugStatus = (bugId) =>
  client.get(`/bugs/${bugId}/status`).then((r) => r.data)

export const getMetrics = () =>
  client.get('/metrics').then((r) => r.data)

export const getTriageHistory = (limit = 50) =>
  client.get('/history/triage', { params: { limit } }).then((r) => r.data)

export const getCaseResult = (caseId) =>
  client.get(`/cases/${caseId}`).then((r) => r.data)
