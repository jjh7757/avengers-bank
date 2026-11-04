import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { accountApi, cardApi, fdsApi, productApi } from '../api/endpoints'
import { useLoad } from '../hooks/useLoad'
import { ACCOUNT_TYPE_LABEL, CARD_TYPE_LABEL, dateTime, FDS_DECISION_LABEL, maskAccount, won } from '../lib/format'

/** 도우미가 무대로 가져오는 화면들. 가져올 때마다 새로 마운트되므로 항상 최신 데이터를 불러온다. */

function Loading({ loading, error }: { loading: boolean; error: string | null }) {
  if (loading) return <p className="muted">불러오는 중…</p>
  if (error) return <p className="error">{error}</p>
  return null
}

export function HomePanel({ name }: { name: string | undefined }) {
  return (
    <div className="stage-welcome">
      <p className="stage-panel-title">{name ? `${name}님, 무엇을 도와드릴까요?` : '무엇을 도와드릴까요?'}</p>
      <p className="muted">메뉴를 찾지 않아도 돼요. 마이크를 누른 채로 말하거나 글로 쓰면 모아가 화면을 가져와요.</p>
    </div>
  )
}

export function AccountsPanel() {
  const { data, error, loading } = useLoad(useCallback(() => accountApi.list(), []))
  return (
    <>
      <p className="stage-panel-title">내 계좌</p>
      <Loading loading={loading} error={error} />
      {data && data.length === 0 && <p className="muted">아직 계좌가 없어요.</p>}
      {data && data.length > 0 && (
        <>
          <ul className="list">
            {data.map((a) => (
              <li key={`${a.account_type}-${a.account_id}`}>
                <Link className="list-item" to={`/accounts/${a.account_type}/${a.account_id}`}>
                  <span>
                    <span className="badge">{ACCOUNT_TYPE_LABEL[a.account_type]}</span>
                    <strong>{a.nickname ?? `${ACCOUNT_TYPE_LABEL[a.account_type]} 계좌`}</strong>
                    <span className="muted small">{maskAccount(a.account_num)}</span>
                  </span>
                  <span className="amount">{won(a.balance)}</span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="total">
            전체 잔액 <strong>{won(data.reduce((sum, a) => sum + a.balance, 0))}</strong>
          </p>
        </>
      )}
    </>
  )
}

export function CardsPanel() {
  const { data, error, loading } = useLoad(useCallback(() => cardApi.list(), []))
  return (
    <>
      <p className="stage-panel-title">내 카드</p>
      <Loading loading={loading} error={error} />
      {data && data.length === 0 && <p className="muted">아직 카드가 없어요.</p>}
      <div className="stage-cards">
        {data?.map((c) => (
          <Link key={`${c.card_type}-${c.card_id}`} className="stage-card-face" to={`/cards/${c.card_type}/${c.card_id}`}>
            <span>{CARD_TYPE_LABEL[c.card_type]}</span>
            <span className="stage-card-num">**** **** **** {c.card_num.slice(-4)}</span>
            <span className="small">이번 달 {won(c.accumulated_amount)}</span>
          </Link>
        ))}
      </div>
    </>
  )
}

/** reply: 모아의 답변. 답변에 이름이 나온 상품(추천한 상품)을 맨 위로 올린다 */
export function ProductsPanel({ reply }: { reply: string }) {
  const load = useCallback(async () => {
    const [accounts, cards] = await Promise.all([productApi.accounts(), productApi.cards()])
    return [...accounts, ...cards]
  }, [])
  const { data: all, error, loading } = useLoad(load)
  const picked = (name: string) => reply.includes(name)
  const data = all && [...all.filter((p) => picked(p.name)), ...all.filter((p) => !picked(p.name))]
  return (
    <>
      <p className="stage-panel-title">상품</p>
      <Loading loading={loading} error={error} />
      <ul className="list">
        {data?.map((p) => (
          <li key={`${p.type}-${p.product_id}`} className={`list-item stage-product ${picked(p.name) ? 'picked' : ''}`}>
            <span>
              <span className="badge">
                {PRODUCT_TYPE_LABEL[p.type]}
                {picked(p.name) && ' · 모아 추천'}
              </span>
              <strong>{p.name}</strong>
              <span className="muted small">{p.description}</span>
            </span>
            {p.interest_rate && Number(p.interest_rate) > 0 && <span className="amount">연 {Number(p.interest_rate)}%</span>}
          </li>
        ))}
      </ul>
    </>
  )
}

const PRODUCT_TYPE_LABEL: Record<string, string> = {
  CHECKING: '입출금',
  DEPOSIT: '예금',
  SAVINGS: '적금',
  CREDIT: '신용카드',
  DEBIT: '체크카드',
}

export function FdsPanel() {
  const { data, error, loading } = useLoad(useCallback(() => fdsApi.logs(), []))
  const recent = data?.slice(0, 5)
  return (
    <>
      <p className="stage-panel-title">최근 이상거래 검사</p>
      <Loading loading={loading} error={error} />
      {recent && recent.length === 0 && <p className="muted">아직 검사한 이체가 없어요.</p>}
      <ul className="list">
        {recent?.map((log) => (
          <li key={log.fds_log_id} className="list-item">
            <span>
              <strong>{won(log.amount)}</strong>
              <span className="muted small">
                {dateTime(log.created_at)} · {log.rule_hits.map((h) => h.name).join(', ') || '위험 신호 없음'}
              </span>
            </span>
            <span className={`risk risk-${log.risk_level.toLowerCase()}`}>{FDS_DECISION_LABEL[log.decision] ?? log.decision}</span>
          </li>
        ))}
      </ul>
      <Link to="/fds">전체 기록 보기</Link>
    </>
  )
}
