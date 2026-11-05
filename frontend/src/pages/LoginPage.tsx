import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client'
import Logo from '../components/Logo'
import { useAuth } from '../auth/useAuth'

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [loginId, setLoginId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(loginId, password)
      navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '로그인하지 못했어요.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <h1 className="brand">
        <Logo size={44} />
      </h1>
      <p className="auth-tagline">말로 하는 은행, 모아가 도와드려요</p>
      <form className="form" onSubmit={submit}>
        <label>
          아이디
          <input value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="button primary" disabled={busy}>
          {busy ? '확인 중…' : '로그인'}
        </button>
      </form>
      <p className="center">
        처음이신가요? <Link to="/signup">회원가입</Link>
      </p>
    </div>
  )
}
