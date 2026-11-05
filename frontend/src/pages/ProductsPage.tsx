import { useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { productApi } from '../api/endpoints'
import type { Product } from '../api/types'
import { useLoad } from '../hooks/useLoad'

const TYPE_LABEL: Record<Product['type'], string> = {
  CHECKING: '입출금',
  DEPOSIT: '예금',
  SAVINGS: '적금',
  CREDIT: '신용카드',
  DEBIT: '체크카드',
}

/** 상품 보기·가입 (/products, ?kind=account|card). "가입하기" → 이용약관·가입 화면 */
export default function ProductsPage() {
  const [params] = useSearchParams()
  const kind = params.get('kind')
  const { data, error, loading } = useLoad(
    useCallback(
      () =>
        Promise.all([
          kind === 'card' ? Promise.resolve([]) : productApi.accounts(),
          kind === 'account' ? Promise.resolve([]) : productApi.cards(),
        ]),
      [kind],
    ),
  )
  const [accounts, cards] = data ?? [[], []]

  const list = (items: Product[], productKind: 'account' | 'card') => (
    <ul className="list">
      {items.map((p) => (
        <li key={`${productKind}-${p.product_id}`}>
          <div className="list-item static">
            <span>
              <span className="badge">{TYPE_LABEL[p.type]}</span>
              <strong>{p.name}</strong>
              <span className="muted small">{p.description}</span>
            </span>
            {p.interest_rate && Number(p.interest_rate) > 0 && <span className="amount">연 {Number(p.interest_rate)}%</span>}
          </div>
          <div className="product-actions">
            <Link className="button small primary" to={`/products/${productKind}/${p.product_id}/signup`}>
              가입하기
            </Link>
          </div>
        </li>
      ))}
    </ul>
  )

  return (
    <section className="page">
      <h1>상품 보기·가입</h1>
      {loading && <p className="muted">불러오는 중…</p>}
      {error && <p className="error">{error}</p>}
      {accounts.length > 0 && (
        <>
          <h2>계좌 상품</h2>
          {list(accounts, 'account')}
        </>
      )}
      {cards.length > 0 && (
        <>
          <h2>카드 상품</h2>
          {list(cards, 'card')}
        </>
      )}
    </section>
  )
}
