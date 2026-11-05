import { CreditCard, Plus } from 'lucide-react'
import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { cardApi } from '../api/endpoints'
import { CardVisual, EmptyState, ErrorState, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { won } from '../lib/format'

export default function CardsPage() {
  const { data: cards, error, loading } = useLoad(useCallback(() => cardApi.list(), []))
  const monthTotal = cards?.reduce((sum, c) => sum + c.accumulated_amount, 0) ?? 0

  return (
    <section className="page">
      <div className="page-title-row">
        <h1>내 카드</h1>
        <Link className="button small" to="/products?kind=card">
          <Plus size={16} aria-hidden="true" /> 카드 발급
        </Link>
      </div>

      {loading && <SkeletonList rows={2} height={180} />}
      {error && <ErrorState message={error} />}
      {cards && cards.length === 0 && (
        <EmptyState
          icon={CreditCard}
          title="아직 카드가 없어요"
          description="체크카드는 입출금 계좌에 연결해서 바로 쓸 수 있어요."
          action={{ to: '/products?kind=card', label: '카드 발급받기' }}
        />
      )}
      {cards && cards.length > 0 && (
        <>
          <p className="total">
            이번 달 사용 <strong>{won(monthTotal)}</strong>
          </p>
          <ul className="card-grid">
            {cards.map((c) => (
              <li key={`${c.card_type}-${c.card_id}`}>
                <Link className="card-link" to={`/cards/${c.card_type}/${c.card_id}`}>
                  <CardVisual type={c.card_type} cardNum={c.card_num} />
                  <span className="card-link-footer">
                    <span className="muted small">이번 달 사용</span>
                    <strong>{won(c.accumulated_amount)}</strong>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
