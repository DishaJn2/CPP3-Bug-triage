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

export const listUsers = () =>
  client.get('/auth/users').then((r) => r.data)

export const createUser = (data) =>
  client.post('/auth/users', data).then((r) => r.data)

export const deleteUser = (email) =>
  client.delete(`/auth/users/${encodeURIComponent(email)}`).then((r) => r.data)
