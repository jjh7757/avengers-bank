import { CreditCard, Landmark, MessageCircle, Settings, Sparkles } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

import DemoClockBadge from './DemoClockBadge'

const NAV = [
  { to: '/', label: '모아', icon: Sparkles, end: true }, // 첫 화면: 도우미가 화면을 가져온다
  { to: '/chat', label: '대화', icon: MessageCircle, end: false },
  { to: '/accounts', label: '계좌', icon: Landmark, end: false },
  { to: '/cards', label: '카드', icon: CreditCard, end: false },
  { to: '/settings', label: '설정', icon: Settings, end: false },
]

export default function Layout() {
  return (
    <div className="app">
      <DemoClockBadge />
      <main className="app-main">
        <Outlet />
      </main>
      <nav className="tabbar" aria-label="주 메뉴">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className="tab">
            <item.icon aria-hidden="true" className="tab-icon" size={24} strokeWidth={2} />
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
