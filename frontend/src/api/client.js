import axios from 'axios'

const client = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 30000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('hpe_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('hpe_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default client
