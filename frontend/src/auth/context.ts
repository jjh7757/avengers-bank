import { createContext } from 'react'

import type { User } from '../api/types'

export interface AuthState {
  user: User | null
  loading: boolean
  login: (loginId: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)
