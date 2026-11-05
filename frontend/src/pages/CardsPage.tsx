import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { cardApi } from '../api/endpoints'
import { useLoad } from '../hooks/useLoad'
import { CARD_TYPE_LABEL, won } from '../lib/format'

export default function CardsPage() {
  const { data: cards, error, loading } = useLoad(useCallback(() => cardApi.list(), []))

  return (
    <section className="page">
      <h1>내 카드</h1>
      <Link className="button small" to="/products?kind=card">
        + 카드 발급받기
      </Link>
      {loading && <p className="muted">불러오는 중…</p>}
      {error && <p className="error">{error}</p>}
      {cards && cards.length === 0 && <p className="muted">아직 카드가 없어요.</p>}
      <ul className="list">
        {cards?.map((c) => (
          <li key={`${c.card_type}-${c.card_id}`}>
            <Link className="list-item" to={`/cards/${c.card_type}/${c.card_id}`}>
              <span>
                <span className="badge">{CARD_TYPE_LABEL[c.card_type]}</span>
                <strong>끝자리 {c.card_num.slice(-4)}</strong>
              </span>
              <span className="amount">
                <span className="muted small">이번 달 </span>
                {won(c.accumulated_amount)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
