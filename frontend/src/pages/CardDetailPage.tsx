import { ChevronLeft, ReceiptText } from 'lucide-react'
import { useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'

import { cardApi } from '../api/endpoints'
import type { CardType } from '../api/types'
import { CardVisual, EmptyState, ErrorState, SkeletonList } from '../components/ui'
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
        <ChevronLeft size={18} aria-hidden="true" /> 내 카드
      </Link>
      {loading && <SkeletonList rows={3} />}
      {error && <ErrorState message={error} />}
      {card && histories && (
        <>
          <h1>
            {CARD_TYPE_LABEL[type]} 끝자리 {card.card_num.slice(-4)}
          </h1>
          <CardVisual type={type} cardNum={card.card_num} />
          <p className="balance">{won(card.accumulated_amount)}</p>
          <p className="muted">
            누적 사용액{card.payment_date ? ` · 매월 ${card.payment_date}일 결제` : ' · 사용 즉시 출금'}
          </p>
          <h2>사용내역</h2>
          {histories.length === 0 && <EmptyState icon={ReceiptText} title="아직 사용내역이 없어요" />}
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
