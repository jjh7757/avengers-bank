import { ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'

/** 고객이 관리자 화면 주소로 들어왔을 때, 또는 쓰는 도중 관리자 권한이 없어졌을 때(403 ADMIN_REQUIRED) */
export function AdminOnlyNotice() {
  return (
    <section className="page">
      <div className="empty-state" role="alert">
        <span className="empty-state-icon" aria-hidden="true">
          <ShieldAlert size={32} />
        </span>
        <p className="empty-state-title">관리자만 쓸 수 있는 화면이에요</p>
        <p className="muted small">관리자 계정으로 로그인했는데 이 안내가 보이면 관리자 권한이 해제된 거예요.</p>
        <Link className="button primary small" to="/">
          홈으로
        </Link>
      </div>
    </section>
  )
}
