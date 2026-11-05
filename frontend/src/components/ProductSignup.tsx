import { useCallback, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { accountApi, cardApi, productApi } from '../api/endpoints'
import type { AccountType, CardType, Product, ProductKind, SignupPrefill } from '../api/types'
import { useLoad } from '../hooks/useLoad'
import { won } from '../lib/format'

/**
 * 상품 가입 화면: 이용약관 → 동의 → 가입 조건 → "가입하기".
 * 앱에서 직접 가입할 때(/products/:kind/:id/signup)와 모아가 가져온 가입 화면(모아 화면의 signup)이 같이 쓴다.
 * 모아는 대화에서 들은 조건을 prefill로 넘길 뿐이고, 동의와 가입은 사용자가 이 화면에서 직접 한다.
 * 서버는 동의한 약관 버전(terms_version)이 지금 버전과 같아야 개설·발급한다.
 */

const TARGET: Record<Product['type'], { kind: ProductKind; type: AccountType | CardType; noun: string }> = {
  CHECKING: { kind: 'account', type: 'checking', noun: '입출금 계좌' },
  DEPOSIT: { kind: 'account', type: 'deposit', noun: '예금 계좌' },
  SAVINGS: { kind: 'account', type: 'savings', noun: '적금 계좌' },
  DEBIT: { kind: 'card', type: 'debit', noun: '체크카드' },
  CREDIT: { kind: 'card', type: 'credit', noun: '신용카드' },
}

export interface SignupResult {
  kind: ProductKind
  type: AccountType | CardType
  id: number
  number: string // 계좌번호 또는 카드번호
}

interface Props {
  kind: ProductKind
  productId: number
  prefill?: SignupPrefill
  onDone?: (result: SignupResult) => void
}

const digits = (text: string) => text.replace(/\D/g, '')
const text = (n: number | undefined) => (n == null ? '' : String(n))

export default function ProductSignup(props: Props) {
  // 가입 요청이 "약관이 바뀌었다"로 거절되면 새 약관으로 화면을 다시 그린다 (입력값·동의는 처음부터)
  const [round, setRound] = useState(0)
  return (
    <SignupForm
      key={round}
      {...props}
      notice={round > 0 ? '이용약관이 바뀌었어요. 새 약관을 읽고 다시 동의해 주세요.' : null}
      onTermsChanged={() => setRound((n) => n + 1)}
    />
  )
}

function SignupForm({
  kind,
  productId,
  prefill = {},
  onDone,
  notice,
  onTermsChanged,
}: Props & { notice: string | null; onTermsChanged: () => void }) {
  const { data, error, loading } = useLoad(
    useCallback(
      () =>
        Promise.all([
          productApi.get(kind, productId),
          productApi.terms(kind, productId),
          kind === 'card' ? accountApi.list() : Promise.resolve([]),
        ]),
      [kind, productId],
    ),
  )
  const [agreed, setAgreed] = useState(false)
  const [termMonths, setTermMonths] = useState(text(prefill.term_months))
  const [monthlyPayment, setMonthlyPayment] = useState(text(prefill.monthly_payment))
  const [depositDate, setDepositDate] = useState(text(prefill.monthly_deposit_date))
  const [checkingId, setCheckingId] = useState(text(prefill.checking_account_id))
  const [paymentDate, setPaymentDate] = useState(text(prefill.payment_date))
  const [nickname, setNickname] = useState('')
  const [saving, setSaving] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(notice)
  const [done, setDone] = useState<SignupResult | null>(null)

  if (loading) return <p className="muted">불러오는 중…</p>
  if (error || !data) return <p className="error">{error ?? '불러오지 못했어요.'}</p>
  const [product, terms, accounts] = data
  const target = TARGET[product.type]
  const checkingAccounts = accounts.filter((a) => a.account_type === 'checking')

  const months = Number(termMonths)
  const payment = Number(monthlyPayment)
  const problems: string[] = []
  if (target.type === 'deposit' || target.type === 'savings') {
    if (!(months >= 1 && months <= 60)) problems.push('가입 기간을 1~60개월로 정해 주세요.')
  }
  if (target.type === 'savings') {
    if (!(payment > 0)) problems.push('매달 넣을 금액을 정해 주세요.')
    if (!(Number(depositDate) >= 1 && Number(depositDate) <= 31)) problems.push('매월 납입일을 1~31일로 정해 주세요.')
  }
  if (target.kind === 'card' && !checkingAccounts.some((a) => String(a.account_id) === checkingId)) {
    problems.push(checkingAccounts.length ? '연결할 입출금 계좌를 골라 주세요.' : '먼저 입출금 계좌를 만들어 주세요.')
  }
  if (target.type === 'credit' && !(Number(paymentDate) >= 1 && Number(paymentDate) <= 31)) {
    problems.push('매월 결제일을 1~31일로 정해 주세요.')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!agreed || problems.length) return
    setSaving(true)
    setSubmitError(null)
    const base = { product_id: productId, terms_version: terms.version }
    try {
      let result: SignupResult
      if (target.kind === 'account') {
        const body =
          target.type === 'checking'
            ? { ...base, nickname: nickname || null }
            : target.type === 'deposit'
              ? { ...base, term_months: months, nickname: nickname || null }
              : {
                  ...base,
                  term_months: months,
                  monthly_payment: payment,
                  monthly_deposit_date: Number(depositDate),
                  nickname: nickname || null,
                }
        const account = await accountApi.open(target.type as AccountType, body)
        result = { kind: 'account', type: target.type, id: account.account_id, number: account.account_num }
      } else {
        const body =
          target.type === 'debit'
            ? { ...base, checking_account_id: Number(checkingId) }
            : { ...base, checking_account_id: Number(checkingId), payment_date: Number(paymentDate) }
        const card = await cardApi.issue(target.type as CardType, body)
        result = { kind: 'card', type: target.type, id: card.card_id, number: card.card_num }
      }
      setDone(result)
      onDone?.(result)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'TERMS_NOT_AGREED') {
        onTermsChanged() // 보는 사이에 약관이 바뀌었다: 새 약관을 다시 보여 주고 다시 동의받는다
        return
      } else {
        setSubmitError(e instanceof ApiError ? e.message : '가입하지 못했어요. 잠시 후 다시 해 주세요.')
      }
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    const path = done.kind === 'account' ? `/accounts/${done.type}/${done.id}` : `/cards/${done.type}/${done.id}`
    return (
      <div className="signup-done" role="status">
        <p className="success">
          <strong>{product.name}</strong> {target.noun}를 만들었어요.
        </p>
        <p className="muted">{done.kind === 'account' ? done.number : `카드 끝자리 ${done.number.slice(-4)}`}</p>
        <Link to={path}>{done.kind === 'account' ? '계좌 보기' : '카드 보기'}</Link>
      </div>
    )
  }

  return (
    <form className="signup" onSubmit={submit}>
      <p className="signup-product">
        <span className="badge">{target.noun}</span>
        <strong>{product.name}</strong>
        {product.interest_rate && Number(product.interest_rate) > 0 && (
          <span className="muted"> 연 {Number(product.interest_rate)}%</span>
        )}
      </p>

      <section className="terms" aria-labelledby={`terms-${kind}-${productId}`}>
        <p id={`terms-${kind}-${productId}`} className="terms-title">
          {terms.title}
        </p>
        <div className="terms-body" tabIndex={0} data-ui-label={`${product.name} 이용약관`}>
          {terms.sections.map((s) => (
            <div key={s.title} className="terms-section">
              <p className="terms-section-title">{s.title}</p>
              <p>{s.text}</p>
            </div>
          ))}
        </div>
        <label className="terms-agree">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
          <span>
            이용약관을 읽었고 동의합니다 <span className="muted small">(필수)</span>
          </span>
        </label>
      </section>

      {(target.type === 'deposit' || target.type === 'savings') && (
        <label>
          가입 기간 (개월)
          <input inputMode="numeric" value={termMonths} onChange={(e) => setTermMonths(digits(e.target.value))} />
        </label>
      )}
      {target.type === 'savings' && (
        <>
          <label>
            매달 넣을 금액 (원)
            <input inputMode="numeric" value={monthlyPayment} onChange={(e) => setMonthlyPayment(digits(e.target.value))} />
            {payment > 0 && <span className="muted small">{won(payment)}</span>}
          </label>
          <label>
            매월 납입일
            <input inputMode="numeric" value={depositDate} onChange={(e) => setDepositDate(digits(e.target.value))} />
          </label>
        </>
      )}
      {target.kind === 'card' && (
        <label>
          {target.type === 'debit' ? '돈이 나갈 입출금 계좌' : '결제 계좌 (입출금)'}
          <select value={checkingId} onChange={(e) => setCheckingId(e.target.value)}>
            <option value="">고르세요</option>
            {checkingAccounts.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.nickname ?? '입출금 계좌'} ({a.account_num.slice(-4)})
              </option>
            ))}
          </select>
        </label>
      )}
      {target.type === 'credit' && (
        <label>
          매월 결제일
          <input inputMode="numeric" value={paymentDate} onChange={(e) => setPaymentDate(digits(e.target.value))} />
        </label>
      )}
      {target.kind === 'account' && (
        <label>
          계좌 별칭 <span className="muted small">(선택, 예: 여행 적금)</span>
          <input value={nickname} maxLength={50} onChange={(e) => setNickname(e.target.value)} />
        </label>
      )}

      {!agreed && <p className="muted small">이용약관에 동의해야 가입할 수 있어요.</p>}
      {agreed && problems.map((p) => <p key={p} className="error small">{p}</p>)}
      {submitError && (
        <p className="error small" role="alert">
          {submitError}
        </p>
      )}
      <button className="button primary" disabled={!agreed || problems.length > 0 || saving}>
        {saving ? '가입하는 중…' : '가입하기'}
      </button>
    </form>
  )
}
