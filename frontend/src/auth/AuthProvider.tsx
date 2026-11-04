import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { tokenStore, UNAUTHORIZED_EVENT } from '../api/client'
import { authApi } from '../api/endpoints'
import type { User } from '../api/types'
import { AuthContext } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // 저장된 토큰이 있으면 내 정보를 받아 올 때까지 로딩
  const [loading, setLoading] = useState(() => tokenStore.get() !== null)

  useEffect(() => {
    if (tokenStore.get()) {
      authApi
        .me()
        .then(setUser, () => setUser(null))
        .finally(() => setLoading(false))
    }
    const onUnauthorized = () => setUser(null)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const refresh = useCallback(async () => {
    setUser(await authApi.me())
  }, [])

  const login = useCallback(async (loginId: string, password: string) => {
    const { access_token } = await authApi.login({ login_id: loginId, password })
    tokenStore.set(access_token)
    setUser(await authApi.me())
  }, [])

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout, refresh }), [user, loading, login, logout, refresh])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
