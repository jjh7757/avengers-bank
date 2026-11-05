import { ChevronRight, KeyRound, LogOut, Mic, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'
import VoiceEnrollment from '../components/VoiceEnrollment'

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
    <section className="page settings-page">
      <h1>설정</h1>
      <div className="profile-card">
        <span className="profile-avatar" aria-hidden="true">
          {user?.name?.slice(0, 1)}
        </span>
        <span className="profile-body">
          <strong>{user?.name}님</strong>
          <span className="muted small">
            {user?.login_id} · {user?.phone}
          </span>
        </span>
      </div>

      <div className="section-card">
        <p className="section-title">
          <KeyRound size={20} aria-hidden="true" /> 이체 PIN {user?.has_pin ? '변경' : '등록'}
          {user?.has_pin && <span className="status-pill">등록됨</span>}
        </p>
        <p className="muted small">평소와 다른 이체를 할 때 숫자 6자리 PIN을 한 번 더 확인해요.</p>
        <form className="form compact" onSubmit={savePin}>
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
      </div>

      <div className="section-card">
        <p className="section-title">
          <Mic size={20} aria-hidden="true" /> 목소리로 이체 승인
        </p>
        <p className="muted small">
          목소리를 등록하면 이체 확인 카드를 "확인 + 숫자"로 말해서 승인해요. 등록한 목소리와 다르면 승인되지 않아요.
        </p>
        <VoiceEnrollment />
      </div>

      <ul className="list">
        <li>
          <Link className="list-item rich" to="/fds">
            <span className="account-icon account-icon-checking" aria-hidden="true">
              <ShieldCheck size={22} />
            </span>
            <span className="list-item-body">
              <strong>이상거래 탐지 기록</strong>
              <span className="muted small">최근 이체를 어떻게 검사했는지 봐요</span>
            </span>
            <ChevronRight className="chevron" size={20} aria-hidden="true" />
          </Link>
        </li>
      </ul>

      <button className="button logout-button" onClick={logout}>
        <LogOut size={18} aria-hidden="true" /> 로그아웃
      </button>
    </section>
  )
}
