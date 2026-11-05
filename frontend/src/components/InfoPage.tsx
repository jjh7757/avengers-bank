import { ChevronLeft, FlaskConical } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

/** 로그인하지 않아도 볼 수 있는 안내 화면(정책·고객센터·앱 정보)의 틀 */
export default function InfoPage({ title, updated, children }: { title: string; updated?: string; children: ReactNode }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  return (
    <section className="page info-page">
      <button
        type="button"
        className="back button link"
        onClick={() => (window.history.length > 1 ? navigate(-1) : navigate(user ? '/settings' : '/login'))}
      >
        <ChevronLeft size={18} aria-hidden="true" /> 뒤로
      </button>
      <h1>{title}</h1>
      {updated && <p className="muted small">시행일 {updated}</p>}
      <p className="demo-notice">
        <FlaskConical size={18} aria-hidden="true" />
        <span>
          AvengersBank는 부트캠프 프로젝트로 만든 <strong>시연용 서비스</strong>예요. 실제 돈이 오가지 않고, 실제 금융회사가
          아니에요.
        </span>
      </p>
      <div className="info-body">{children}</div>
      {!user && (
        <p className="center">
          <Link to="/login">로그인 화면으로</Link>
        </p>
      )}
    </section>
  )
}
