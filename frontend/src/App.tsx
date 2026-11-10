import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth/useAuth'
import { AdminOnlyNotice } from './components/AdminOnlyNotice'
import IdleGuard from './components/IdleGuard'
import Layout from './components/Layout'
import { LogoMark } from './components/Logo'
import AboutPage from './pages/AboutPage'
import AccountDetailPage from './pages/AccountDetailPage'
import AccountsPage from './pages/AccountsPage'
import AdminTreasuryPage from './pages/AdminTreasuryPage'
import CardDetailPage from './pages/CardDetailPage'
import CardsPage from './pages/CardsPage'
import ChatPage from './pages/ChatPage'
import FdsLogsPage from './pages/FdsLogsPage'
import LoginPage from './pages/LoginPage'
import ProductSignupPage from './pages/ProductSignupPage'
import PrivacyPage from './pages/PrivacyPage'
import ProductsPage from './pages/ProductsPage'
import SettingsPage from './pages/SettingsPage'
import SignupPage from './pages/SignupPage'
import SupportPage from './pages/SupportPage'
import TransferPage from './pages/TransferPage'
import StagePage from './stage/StagePage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading)
    return (
      <div className="splash" role="status" aria-label="불러오는 중">
        <LogoMark size={56} />
      </div>
    )
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

/** 관리자 화면: 서버도 403 ADMIN_REQUIRED로 막지만 화면에서도 막는다 (고객이면 "관리자만" 안내 + 홈으로) */
function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user?.role !== 'ADMIN') return <AdminOnlyNotice />
  return children
}

/** 첫 화면: 고객은 도우미(모아). 관리자는 고객 계좌가 없어 모아가 할 일이 없으므로 자금 관리로 보낸다 */
function Home() {
  const { user } = useAuth()
  if (user?.role === 'ADMIN') return <Navigate to="/admin/treasury" replace />
  return <StagePage />
}

export default function App() {
  return (
    <>
      <IdleGuard />
      <AppRoutes />
    </>
  )
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      {/* 로그인 없이 볼 수 있는 안내 */}
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/support" element={<SupportPage />} />
      <Route path="/about" element={<AboutPage />} />
      {/* 첫 화면 = 도우미 화면(모아). 넓은 무대를 쓰므로 하단 탭(Layout) 없이 연다 */}
      <Route
        path="/"
        element={
          <RequireAuth>
            <Home />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/accounts" element={<AccountsPage />} />
        <Route path="/accounts/:type/:id" element={<AccountDetailPage />} />
        <Route path="/transfer" element={<TransferPage />} />
        <Route path="/cards" element={<CardsPage />} />
        <Route path="/cards/:type/:id" element={<CardDetailPage />} />
        <Route path="/products" element={<ProductsPage />} />
        <Route path="/products/:kind/:id/signup" element={<ProductSignupPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/fds" element={<FdsLogsPage />} />
        <Route
          path="/admin/treasury"
          element={
            <RequireAdmin>
              <AdminTreasuryPage />
            </RequireAdmin>
          }
        />
      </Route>
      <Route path="/stage" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
