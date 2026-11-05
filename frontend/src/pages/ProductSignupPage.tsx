import { ChevronLeft } from 'lucide-react'
import { Link, Navigate, useParams } from 'react-router-dom'

import ProductSignup from '../components/ProductSignup'

/** 앱에서 직접 가입 (/products/:kind/:id/signup): 이용약관 동의 → 조건 → 가입하기 */
export default function ProductSignupPage() {
  const params = useParams()
  const kind = params.kind
  const productId = Number(params.id)
  if ((kind !== 'account' && kind !== 'card') || !Number.isInteger(productId) || productId < 1) {
    return <Navigate to="/products" replace />
  }
  return (
    <section className="page">
      <Link to={`/products?kind=${kind}`} className="back">
        <ChevronLeft size={18} aria-hidden="true" /> 상품 보기
      </Link>
      <h1>상품 가입</h1>
      <ProductSignup key={`${kind}-${productId}`} kind={kind} productId={productId} />
    </section>
  )
}
