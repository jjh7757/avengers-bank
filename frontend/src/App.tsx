import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth/useAuth'
import Layout from './components/Layout'
import AccountDetailPage from './pages/AccountDetailPage'
import AccountsPage from './pages/AccountsPage'
import CardDetailPage from './pages/CardDetailPage'
import CardsPage from './pages/CardsPage'
import ChatPage from './pages/ChatPage'
import FdsLogsPage from './pages/FdsLogsPage'
import LoginPage from './pages/LoginPage'
import ProductSignupPage from './pages/ProductSignupPage'
import ProductsPage from './pages/ProductsPage'
import SettingsPage from './pages/SettingsPage'
import SignupPage from './pages/SignupPage'
import TransferPage from './pages/TransferPage'
import StagePage from './stage/StagePage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <p className="center muted">불러오는 중…</p>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      {/* 첫 화면 = 도우미 화면(모아). 넓은 무대를 쓰므로 하단 탭(Layout) 없이 연다 */}
      <Route
        path="/"
        element={
          <RequireAuth>
            <StagePage />
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
      </Route>
      <Route path="/stage" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
