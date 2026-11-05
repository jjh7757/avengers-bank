import { ArrowLeftRight, ChevronLeft, ReceiptText } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { accountApi } from '../api/endpoints'
import type { AccountDetail, AccountType } from '../api/types'
import TransferLimitForm from '../components/TransferLimitForm'
import { AccountIcon, EmptyState, ErrorState, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { ACCOUNT_TYPE_LABEL, HISTORY_TYPE_LABEL, dateTime, signedWon, won } from '../lib/format'

export default function AccountDetailPage() {
  const params = useParams()
  const type = params.type as AccountType
  const id = Number(params.id)
  const { data, error, loading } = useLoad(
    useCallback(() => Promise.all([accountApi.get(type, id), accountApi.histories(type, id)]), [type, id]),
  )
  const [loaded, histories] = data ?? [null, null]
  const [updated, setUpdated] = useState<AccountDetail | null>(null) // 한도를 바꾼 뒤의 계좌
  const account = updated?.account_id === id && type === 'checking' ? updated : loaded

  return (
    <section className="page">
      <Link to="/accounts" className="back">
        <ChevronLeft size={18} aria-hidden="true" /> 내 계좌
      </Link>
      {loading && <SkeletonList rows={4} />}
      {error && <ErrorState message={error} />}
      {account && histories && (
        <>
          <div className="hero-card">
            <p className="hero-label hero-title">
              <AccountIcon type={type} />
              {account.nickname ?? `${ACCOUNT_TYPE_LABEL[type]} 계좌`}
            </p>
            <p className="hero-sub">
              {ACCOUNT_TYPE_LABEL[type]} · {account.account_num}
            </p>
            <p className="hero-amount">{won(account.balance)}</p>
            {type === 'checking' && (
              <div className="hero-actions">
                <Link className="button hero-button" to={`/transfer?from=${account.account_id}`}>
                  <ArrowLeftRight size={18} aria-hidden="true" /> 이 계좌에서 이체하기
                </Link>
              </div>
            )}
          </div>
          <dl className="facts">
            {account.per_transfer_limit != null && (
              <>
                <dt>1회 이체 한도</dt>
                <dd>{won(account.per_transfer_limit)}</dd>
                <dt>1일 이체 한도</dt>
                <dd>{won(account.daily_transfer_limit ?? 0)}</dd>
              </>
            )}
            {account.monthly_payment != null && (
              <>
                <dt>월 납입액</dt>
                <dd>
                  {won(account.monthly_payment)} (매월 {account.monthly_deposit_date}일)
                </dd>
              </>
            )}
            {account.maturity_date && (
              <>
                <dt>만기일</dt>
                <dd>{account.maturity_date}</dd>
              </>
            )}
          </dl>
          {type === 'checking' && <TransferLimitForm key={account.account_id} account={account} onSaved={setUpdated} />}

          <h2>거래내역</h2>
          {histories.length === 0 && <EmptyState icon={ReceiptText} title="아직 거래내역이 없어요" />}
          <ul className="list">
            {histories.map((h) => (
              <li key={h.history_id} className="list-item static">
                <span>
                  <strong>{HISTORY_TYPE_LABEL[h.type] ?? h.type}</strong>
                  <span className="muted small">{dateTime(h.date)}</span>
                </span>
                <span className={`amount ${h.amount < 0 ? 'minus' : 'plus'}`}>{signedWon(h.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
