import { ChevronRight, FileText, Headphones, Info, KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'
import PinPad from '../components/PinPad'
import { dateTime } from '../lib/format'

const INFO_LINKS = [
  { to: '/support', icon: Headphones, title: '고객센터', desc: '자주 묻는 질문, 문의, 사고 신고' },
  { to: '/privacy', icon: FileText, title: '개인정보처리방침', desc: '어떤 정보를 왜, 얼마나 보관하는지' },
  { to: '/about', icon: Info, title: '앱 정보', desc: '버전, 오픈소스 라이선스' },
]

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
          <span className="muted small">
            지난 로그인 {user?.previous_login_at ? dateTime(user.previous_login_at) : '없음 (처음 로그인)'}
          </span>
        </span>
      </div>
      <p className="security-note">
        <ShieldCheck size={16} aria-hidden="true" /> 모르는 로그인 기록이 있으면 비밀번호와 PIN을 바로 바꿔 주세요. 10분
        동안 사용하지 않으면 자동으로 로그아웃돼요.
      </p>

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
          <PinPad value={pin} onChange={setPin} label="새 PIN (숫자 6자리)" />
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
        {INFO_LINKS.map(({ to, icon: Icon, title, desc }) => (
          <li key={to}>
            <Link className="list-item rich" to={to}>
              <span className="account-icon account-icon-checking" aria-hidden="true">
                <Icon size={22} />
              </span>
              <span className="list-item-body">
                <strong>{title}</strong>
                <span className="muted small">{desc}</span>
              </span>
              <ChevronRight className="chevron" size={20} aria-hidden="true" />
            </Link>
          </li>
        ))}
      </ul>

      <button className="button logout-button" onClick={() => logout()}>
        <LogOut size={18} aria-hidden="true" /> 로그아웃
      </button>
    </section>
  )
}
