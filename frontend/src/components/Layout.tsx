import { CreditCard, Landmark, MessageCircle, Settings, Sparkles, Vault } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import DemoClockBadge from './DemoClockBadge'

const NAV = [
  { to: '/', label: '모아', icon: Sparkles, end: true }, // 첫 화면: 도우미가 화면을 가져온다
  { to: '/chat', label: '대화', icon: MessageCircle, end: false },
  { to: '/accounts', label: '계좌', icon: Landmark, end: false },
  { to: '/cards', label: '카드', icon: CreditCard, end: false },
  { to: '/settings', label: '설정', icon: Settings, end: false },
]

/** 관리자는 고객 계좌·카드가 없다: 자금 관리와 설정(로그아웃)만 */
const ADMIN_NAV = [
  { to: '/admin/treasury', label: '자금 관리', icon: Vault, end: false },
  { to: '/settings', label: '설정', icon: Settings, end: false },
]

export default function Layout() {
  const { user } = useAuth()
  const nav = user?.role === 'ADMIN' ? ADMIN_NAV : NAV
  return (
    <div className="app">
      <DemoClockBadge />
      <main className="app-main">
        <Outlet />
      </main>
      <nav className="tabbar" aria-label="주 메뉴">
        {nav.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className="tab">
            <item.icon aria-hidden="true" className="tab-icon" size={24} strokeWidth={2} />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
