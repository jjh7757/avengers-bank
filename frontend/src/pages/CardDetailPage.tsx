import { useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'

import { cardApi } from '../api/endpoints'
import type { CardType } from '../api/types'
import { useLoad } from '../hooks/useLoad'
import { CARD_TYPE_LABEL, dateTime, won } from '../lib/format'

export default function CardDetailPage() {
  const params = useParams()
  const type = params.type as CardType
  const id = Number(params.id)
  const { data, error, loading } = useLoad(
    useCallback(() => Promise.all([cardApi.get(type, id), cardApi.histories(type, id)]), [type, id]),
  )
  const [card, histories] = data ?? [null, null]

  return (
    <section className="page">
      <Link to="/cards" className="back">
        ← 내 카드
      </Link>
      {loading && <p className="muted">불러오는 중…</p>}
      {error && <p className="error">{error}</p>}
      {card && histories && (
        <>
          <h1>
            {CARD_TYPE_LABEL[type]} 끝자리 {card.card_num.slice(-4)}
          </h1>
          <p className="balance">{won(card.accumulated_amount)}</p>
          <p className="muted">
            누적 사용액{card.payment_date ? ` · 매월 ${card.payment_date}일 결제` : ' · 사용 즉시 출금'}
          </p>
          <h2>사용내역</h2>
          {histories.length === 0 && <p className="muted">사용내역이 없어요.</p>}
          <ul className="list">
            {histories.map((h) => (
              <li key={h.history_id} className="list-item static">
                <span>
                  <strong>{h.place_of_use}</strong>
                  <span className="muted small">{dateTime(h.time)}</span>
                </span>
                <span className="amount minus">-{won(h.used_amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
