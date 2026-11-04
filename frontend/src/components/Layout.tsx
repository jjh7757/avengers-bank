import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/', label: '대화', icon: '💬', end: true },
  { to: '/accounts', label: '계좌', icon: '🏦', end: false },
  { to: '/cards', label: '카드', icon: '💳', end: false },
  { to: '/settings', label: '설정', icon: '⚙️', end: false },
]

export default function Layout() {
  return (
    <div className="app">
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
