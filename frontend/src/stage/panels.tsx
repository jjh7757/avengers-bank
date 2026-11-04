import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { accountApi, cardApi, fdsApi, productApi } from '../api/endpoints'
import type { AccountDetail, AccountType, CardType, UiSelected } from '../api/types'
import TransferLimitForm from '../components/TransferLimitForm'
import { useLoad } from '../hooks/useLoad'
import {
  ACCOUNT_TYPE_LABEL,
  CARD_TYPE_LABEL,
  dateTime,
  FDS_DECISION_LABEL,
  HISTORY_TYPE_LABEL,
  maskAccount,
  signedWon,
  won,
} from '../lib/format'
import { selectionKey, type Pick } from './selection'

/**
 * 도우미가 무대로 가져오는 화면들. 가져올 때마다 새로 마운트되므로 항상 최신 데이터를 불러온다.
 * 목록 항목은 눌러서 고를 수 있고("이거 가입해줘"), data-ui-label을 단 항목은 "화면에 보이는 항목"으로
 * 메시지와 함께 에이전트에게 간다 (StagePage가 보낼 때 모은다).
 */

function PickButton({
  pick,
  selected,
  className = 'list-item',
  children,
}: {
  pick: Pick
  selected: UiSelected
  className?: string
  children: ReactNode
}) {
  const on = pick.selectedKey === selectionKey(selected)
  return (
    <button
      type="button"
      className={`${className} stage-pick ${on ? 'selected' : ''}`}
      aria-pressed={on}
      data-ui-label={selected.label}
      onClick={() => pick.onSelect(selected)}
    >
      {children}
    </button>
  )
}

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

export function AccountsPanel({ pick }: { pick: Pick }) {
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
                <PickButton
                  pick={pick}
                  selected={{
                    kind: 'account',
                    label: a.nickname ?? `${ACCOUNT_TYPE_LABEL[a.account_type]} 계좌`,
                    account_type: a.account_type,
                    account_id: a.account_id,
                  }}
                >
                  <span>
                    <span className="badge">{ACCOUNT_TYPE_LABEL[a.account_type]}</span>
                    <strong>{a.nickname ?? `${ACCOUNT_TYPE_LABEL[a.account_type]} 계좌`}</strong>
                    <span className="muted small">{maskAccount(a.account_num)}</span>
                  </span>
                  <span className="amount">{won(a.balance)}</span>
                </PickButton>
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

const RECENT = 8 // 무대에는 최근 거래만. 전체는 상세 화면에서

/** 계좌 하나: 잔액·한도(입출금이면 한도 변경 폼)·최근 거래 */
export function AccountPanel({ type, id }: { type: AccountType; id: number }) {
  const { data, error, loading } = useLoad(
    useCallback(() => Promise.all([accountApi.get(type, id), accountApi.histories(type, id)]), [type, id]),
  )
  const [updated, setUpdated] = useState<AccountDetail | null>(null)
  const [loaded, histories] = data ?? [null, null]
  const account = updated ?? loaded
  return (
    <>
      <Loading loading={loading} error={error} />
      {account && histories && (
        <>
          <p className="stage-panel-title">
            {account.nickname ?? `${ACCOUNT_TYPE_LABEL[type]} 계좌`}{' '}
            <span className="muted small">{maskAccount(account.account_num)}</span>
          </p>
          <p className="balance">{won(account.balance)}</p>
          {account.per_transfer_limit != null && (
            <p className="muted small">
              이체 한도 1회 {won(account.per_transfer_limit)} · 1일 {won(account.daily_transfer_limit ?? 0)}
            </p>
          )}
          {type === 'checking' && <TransferLimitForm key={account.account_id} account={account} onSaved={setUpdated} />}
          <p className="stage-subtitle">최근 거래</p>
          {histories.length === 0 && <p className="muted">거래내역이 없어요.</p>}
          <ul className="list">
            {histories.slice(0, RECENT).map((h) => (
              <li key={h.history_id} className="list-item static">
                <span>
                  <strong>{HISTORY_TYPE_LABEL[h.type] ?? h.type}</strong>
                  <span className="muted small">{dateTime(h.date)}</span>
                </span>
                <span className={`amount ${h.amount < 0 ? 'minus' : 'plus'}`}>{signedWon(h.amount)}</span>
              </li>
            ))}
          </ul>
          <Link to={`/accounts/${type}/${id}`}>전체 거래내역 보기</Link>
        </>
      )}
    </>
  )
}

/** 카드 하나: 카드 모양·이번 달 사용액·최근 사용내역 */
export function CardPanel({ type, id }: { type: CardType; id: number }) {
  const { data, error, loading } = useLoad(
    useCallback(() => Promise.all([cardApi.get(type, id), cardApi.histories(type, id)]), [type, id]),
  )
  const [card, histories] = data ?? [null, null]
  return (
    <>
      <Loading loading={loading} error={error} />
      {card && histories && (
        <>
          <p className="stage-panel-title">내 카드</p>
          <div className="stage-card-face">
            <span>{CARD_TYPE_LABEL[type]}</span>
            <span className="stage-card-num">**** **** **** {card.card_num.slice(-4)}</span>
            <span className="small">
              이번 달 {won(card.accumulated_amount)}
              {card.payment_date ? ` · 매월 ${card.payment_date}일 결제` : ' · 사용 즉시 출금'}
            </span>
          </div>
          <p className="stage-subtitle">최근 사용</p>
          {histories.length === 0 && <p className="muted">사용내역이 없어요.</p>}
          <ul className="list">
            {histories.slice(0, RECENT).map((h) => (
              <li key={h.history_id} className="list-item static">
                <span>
                  <strong>{h.place_of_use}</strong>
                  <span className="muted small">{dateTime(h.time)}</span>
                </span>
                <span className="amount minus">-{won(h.used_amount)}</span>
              </li>
            ))}
          </ul>
          <Link to={`/cards/${type}/${id}`}>전체 사용내역 보기</Link>
        </>
      )}
    </>
  )
}

export function CardsPanel({ pick }: { pick: Pick }) {
  const { data, error, loading } = useLoad(useCallback(() => cardApi.list(), []))
  return (
    <>
      <p className="stage-panel-title">내 카드</p>
      <Loading loading={loading} error={error} />
      {data && data.length === 0 && <p className="muted">아직 카드가 없어요.</p>}
      <div className="stage-cards">
        {data?.map((c) => (
          <PickButton
            key={`${c.card_type}-${c.card_id}`}
            pick={pick}
            className="stage-card-face"
            selected={{
              kind: 'card',
              label: `${CARD_TYPE_LABEL[c.card_type]} 끝자리 ${c.card_num.slice(-4)}`,
              card_type: c.card_type,
              card_id: c.card_id,
            }}
          >
            <span>{CARD_TYPE_LABEL[c.card_type]}</span>
            <span className="stage-card-num">**** **** **** {c.card_num.slice(-4)}</span>
            <span className="small">이번 달 {won(c.accumulated_amount)}</span>
          </PickButton>
        ))}
      </div>
    </>
  )
}

export interface ProductFilter {
  kind?: 'account' | 'card' | 'all'
  keyword?: string
  productId?: number
}

/**
 * 상품 목록. kind로 계좌/카드 상품만 보여 주고, 모아가 찾은 상품(product_id·키워드)과
 * 답변에 이름이 나온 상품(추천한 상품)을 맨 위로 올린다.
 */
export function ProductsPanel({
  reply,
  kind = 'all',
  keyword,
  productId,
  pick,
}: { reply: string; pick: Pick } & ProductFilter) {
  const load = useCallback(async () => {
    const [accounts, cards] = await Promise.all([
      kind === 'card' ? [] : productApi.accounts(),
      kind === 'account' ? [] : productApi.cards(),
    ])
    return [...accounts, ...cards]
  }, [kind])
  const { data: all, error, loading } = useLoad(load)
  const recommended = (p: { product_id: number; name: string; description: string }) =>
    p.product_id === productId ||
    reply.includes(p.name) ||
    (!!keyword && (p.name.includes(keyword) || p.description.includes(keyword)))
  const data = all && [...all.filter(recommended), ...all.filter((p) => !recommended(p))]
  return (
    <>
      <p className="stage-panel-title">{kind === 'account' ? '계좌 상품' : kind === 'card' ? '카드 상품' : '상품'}</p>
      <Loading loading={loading} error={error} />
      <ul className="list">
        {data?.map((p) => (
          <li key={`${p.type}-${p.product_id}`}>
            <PickButton
              pick={pick}
              className={`list-item stage-product ${recommended(p) ? 'recommended' : ''}`}
              selected={{
                kind: 'product',
                label: p.name,
                product_kind: p.type === 'CREDIT' || p.type === 'DEBIT' ? 'card' : 'account',
                product_id: p.product_id,
              }}
            >
              <span>
                <span className="badge">
                  {PRODUCT_TYPE_LABEL[p.type]}
                  {recommended(p) && ' · 모아 추천'}
                </span>
                <strong>{p.name}</strong>
                <span className="muted small">{p.description}</span>
              </span>
              {p.interest_rate && Number(p.interest_rate) > 0 && <span className="amount">연 {Number(p.interest_rate)}%</span>}
            </PickButton>
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
