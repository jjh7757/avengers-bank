import { NavLink, Outlet } from 'react-router-dom'

import DemoClockBadge from './DemoClockBadge'

const NAV = [
  { to: '/', label: '모아', icon: '🐷', end: true }, // 첫 화면: 도우미가 화면을 가져온다
  { to: '/chat', label: '대화', icon: '💬', end: false },
  { to: '/accounts', label: '계좌', icon: '🏦', end: false },
  { to: '/cards', label: '카드', icon: '💳', end: false },
  { to: '/settings', label: '설정', icon: '⚙️', end: false },
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
            <span aria-hidden="true" className="tab-icon">
              {item.icon}
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
