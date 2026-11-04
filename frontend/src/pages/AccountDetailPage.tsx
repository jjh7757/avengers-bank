import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { accountApi } from '../api/endpoints'
import type { AccountDetail, AccountType } from '../api/types'
import TransferLimitForm from '../components/TransferLimitForm'
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
        ← 내 계좌
      </Link>
      {loading && <p className="muted">불러오는 중…</p>}
      {error && <p className="error">{error}</p>}
      {account && histories && (
        <>
          <h1>{account.nickname ?? `${ACCOUNT_TYPE_LABEL[type]} 계좌`}</h1>
          <p className="muted">{account.account_num}</p>
          <p className="balance">{won(account.balance)}</p>
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
          {histories.length === 0 && <p className="muted">거래내역이 없어요.</p>}
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
