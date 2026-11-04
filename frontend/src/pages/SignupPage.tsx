import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError } from '../api/client'
import { authApi } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'

export default function SignupPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ login_id: '', password: '', name: '', nick_name: '', phone: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const field = (key: keyof typeof form) => ({
    value: form[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value }),
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await authApi.signup({ ...form, nick_name: form.nick_name || null })
      await login(form.login_id, form.password)
      navigate('/', { replace: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '가입하지 못했어요.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <h1 className="brand">회원가입</h1>
      <form className="form" onSubmit={submit}>
        <label>
          아이디 <span className="muted">(4자 이상)</span>
          <input {...field('login_id')} minLength={4} maxLength={50} autoComplete="username" required />
        </label>
        <label>
          비밀번호 <span className="muted">(8자 이상)</span>
          <input type="password" {...field('password')} minLength={8} autoComplete="new-password" required />
        </label>
        <label>
          이름
          <input {...field('name')} maxLength={50} autoComplete="name" required />
        </label>
        <label>
          닉네임 <span className="muted">(선택)</span>
          <input {...field('nick_name')} maxLength={50} />
        </label>
        <label>
          전화번호
          <input {...field('phone')} placeholder="010-1234-5678" minLength={9} maxLength={20} autoComplete="tel" required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="button primary" disabled={busy}>
          {busy ? '가입 중…' : '가입하기'}
        </button>
      </form>
      <p className="center">
        이미 계정이 있나요? <Link to="/login">로그인</Link>
      </p>
    </div>
  )
}
