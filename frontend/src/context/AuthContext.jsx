import { createContext, useContext, useState, useEffect } from 'react'
import { login as apiLogin, getMe } from '../api/auth'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('hpe_token')
    if (token) {
      getMe()
        .then((u) => setUser(u))
        .catch(() => localStorage.removeItem('hpe_token'))
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = async (email, password) => {
    const data = await apiLogin(email, password)
    localStorage.setItem('hpe_token', data.access_token)
    setUser({ email: data.user_id, role: data.role })
    return data
  }

  const logout = () => {
    localStorage.removeItem('hpe_token')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, isAuthenticated: !!user, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
