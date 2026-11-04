import { useContext } from 'react'

import { AuthContext, type AuthState } from './context'

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('AuthProvider 안에서만 쓸 수 있습니다.')
  return context
}
