import { ArrowLeftRight, ChevronRight, Plus, Wallet } from 'lucide-react'
import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { accountApi } from '../api/endpoints'
import { AccountIcon, EmptyState, ErrorState, Skeleton, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { ACCOUNT_TYPE_LABEL, won } from '../lib/format'

export default function AccountsPage() {
  const { data: accounts, error, loading } = useLoad(useCallback(() => accountApi.list(), []))
  const total = accounts?.reduce((sum, a) => sum + a.balance, 0) ?? 0

  return (
    <section className="page">
      <h1>내 계좌</h1>

      <div className="hero-card">
        <p className="hero-label">전체 잔액</p>
        <p className="hero-amount">{loading ? <Skeleton width={180} height={36} /> : won(total)}</p>
        {accounts && <p className="hero-sub">계좌 {accounts.length}개</p>}
        <div className="hero-actions">
          <Link className="button hero-button" to="/transfer">
            <ArrowLeftRight size={18} aria-hidden="true" /> 이체하기
          </Link>
          <Link className="button hero-button ghost" to="/products?kind=account">
            <Plus size={18} aria-hidden="true" /> 새 계좌
          </Link>
        </div>
      </div>

      {loading && <SkeletonList rows={3} />}
      {error && <ErrorState message={error} />}
      {accounts && accounts.length === 0 && (
        <EmptyState
          icon={Wallet}
          title="아직 계좌가 없어요"
          description="입출금 통장을 먼저 만들면 이체와 카드 발급을 할 수 있어요."
          action={{ to: '/products?kind=account', label: '계좌 만들기' }}
        />
      )}
      {accounts && accounts.length > 0 && (
        <ul className="list">
          {accounts.map((a) => (
            <li key={`${a.account_type}-${a.account_id}`}>
              <Link className="list-item rich" to={`/accounts/${a.account_type}/${a.account_id}`}>
                <AccountIcon type={a.account_type} />
                <span className="list-item-body">
                  <strong>{a.nickname ?? `${ACCOUNT_TYPE_LABEL[a.account_type]} 계좌`}</strong>
                  <span className="muted small">{a.account_num}</span>
                </span>
                <span className="amount">{won(a.balance)}</span>
                <ChevronRight className="chevron" size={20} aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
