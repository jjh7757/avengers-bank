import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { accountApi } from '../api/endpoints'
import { useLoad } from '../hooks/useLoad'
import { ACCOUNT_TYPE_LABEL, maskAccount, won } from '../lib/format'

export default function AccountsPage() {
  const { data: accounts, error, loading } = useLoad(useCallback(() => accountApi.list(), []))
  const total = accounts?.reduce((sum, a) => sum + a.balance, 0) ?? 0

  return (
    <section className="page">
      <h1>내 계좌</h1>
      {loading && <p className="muted">불러오는 중…</p>}
      {error && <p className="error">{error}</p>}
      {accounts && (
        <>
          <p className="total">
            전체 잔액 <strong>{won(total)}</strong>
          </p>
          {accounts.length === 0 && <p className="muted">아직 계좌가 없어요.</p>}
          <ul className="list">
            {accounts.map((a) => (
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
        </>
      )}
    </section>
  )
}
