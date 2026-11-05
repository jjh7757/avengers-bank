import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { refreshAccessToken, tokenStore, UNAUTHORIZED_EVENT } from '../api/client'
import { authApi } from '../api/endpoints'
import type { User } from '../api/types'
import { AuthContext, type LogoutReason } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // 처음에는 refresh 쿠키로 로그인 상태를 되살릴 때까지 로딩 (access 토큰은 메모리에만 있어서 새로고침하면 사라진다)
  const [loading, setLoading] = useState(true)
  const [logoutReason, setLogoutReason] = useState<LogoutReason | null>(null)

  useEffect(() => {
    let alive = true
    refreshAccessToken()
      .then((ok) => (ok ? authApi.me() : null))
      .then((me) => alive && setUser(me), () => alive && setUser(null))
      .finally(() => alive && setLoading(false))
    const onUnauthorized = () => {
      setUser(null)
      setLogoutReason('expired')
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => {
      alive = false
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
  }, [])

  const refresh = useCallback(async () => {
    setUser(await authApi.me())
  }, [])

  const login = useCallback(async (loginId: string, password: string) => {
    const { access_token } = await authApi.login({ login_id: loginId, password })
    tokenStore.set(access_token)
    setLogoutReason(null)
    setUser(await authApi.me())
  }, [])

  const logout = useCallback((reason: LogoutReason = 'user') => {
    authApi.logout().catch(() => {}) // 쿠키 폐기. 실패해도 화면은 로그아웃한다
    tokenStore.clear()
    setLogoutReason(reason)
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, logoutReason, login, logout, refresh }),
    [user, loading, logoutReason, login, logout, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
