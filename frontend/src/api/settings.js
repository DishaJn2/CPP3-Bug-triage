import client from './client'

export const getConnections = () =>
  client.get('/settings/connections').then((r) => r.data)

export const addConnection = (data) =>
  client.post('/settings/connections', data).then((r) => r.data)

export const updateConnection = (sourceId, data) =>
  client.put(`/settings/connections/${sourceId}`, data).then((r) => r.data)

export const removeConnection = (sourceId) =>
  client.delete(`/settings/connections/${sourceId}`).then((r) => r.data)

export const testConnection = (sourceId) =>
  client.post(`/settings/connections/${sourceId}/test`).then((r) => r.data)
