import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'

export default function SettingsPage() {
  const { user, logout, refresh } = useAuth()
  const [password, setPassword] = useState('')
  const [pin, setPin] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  async function savePin(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      await authApi.setPin(password, pin)
      await refresh()
      setPassword('')
      setPin('')
      setMessage({ ok: true, text: '이체 PIN을 등록했어요.' })
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : '등록하지 못했어요.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="page">
      <h1>설정</h1>
      <div className="panel">
        <p>
          <strong>{user?.name}</strong>님 <span className="muted">({user?.login_id})</span>
        </p>
        <p className="muted">{user?.phone}</p>
      </div>

      <h2>이체 PIN {user?.has_pin ? '변경' : '등록'}</h2>
      <p className="muted">평소와 다른 이체를 할 때 숫자 6자리 PIN을 한 번 더 확인해요.</p>
      <form className="form" onSubmit={savePin}>
        <label>
          로그인 비밀번호
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label>
          새 PIN (숫자 6자리)
          <input
            type="password"
            inputMode="numeric"
            pattern="\d{6}"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
            autoComplete="off"
            required
          />
        </label>
        {message && (
          <p className={message.ok ? 'success' : 'error'} role="status">
            {message.text}
          </p>
        )}
        <button className="button primary" disabled={busy || pin.length !== 6}>
          {user?.has_pin ? 'PIN 변경' : 'PIN 등록'}
        </button>
      </form>

      <h2>기타</h2>
      <ul className="list">
        <li>
          <Link className="list-item" to="/fds">
            <strong>이상거래 탐지 기록</strong>
            <span className="muted">›</span>
          </Link>
        </li>
      </ul>
      <button className="button" onClick={logout}>
        로그아웃
      </button>
    </section>
  )
}
