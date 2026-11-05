import { createContext } from 'react'

import type { User } from '../api/types'

/** user: 직접 로그아웃 / idle: 오래 사용하지 않아 자동 로그아웃 / expired: 로그인 유지가 끝남 */
export type LogoutReason = 'user' | 'idle' | 'expired'

export interface AuthState {
  user: User | null
  loading: boolean
  /** 왜 로그아웃됐는지 (로그인 화면 안내 문구) */
  logoutReason: LogoutReason | null
  login: (loginId: string, password: string) => Promise<void>
  logout: (reason?: LogoutReason) => void
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)
