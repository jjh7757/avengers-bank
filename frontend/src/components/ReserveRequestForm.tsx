import { useState, type FormEvent } from 'react'

import { adminApi } from '../api/endpoints'
import type { ReserveKind, Treasury } from '../api/types'
import { koreanWon, won } from '../lib/format'
import { adminErrorMessage, isAdminRevoked, RESERVE_KIND_LABEL } from '../lib/treasury'

const MAX_AMOUNT = 1_000_000_000_000 // 백엔드 reserve_requests.MAX_AMOUNT (1조)
const MEMO_MAX = 200

type Result = { tone: 'success' | 'caution' | 'error'; text: string }

interface Props {
  treasury: Treasury
  /** 신청 뒤 현황·내역·감사 로그를 다시 읽는다 */
  onDone: () => void
  onRevoked: () => void
}

/** 예치금 입금·인출 신청. 보내기 전에 확인 단계를 거친다. 허브 관리자가 승인해야 잔액이 바뀐다 */
export default function ReserveRequestForm({ treasury, onDone, onRevoked }: Props) {
  const [kind, setKind] = useState<ReserveKind>('DEPOSIT')
  const [amount, setAmount] = useState(0)
  const [memo, setMemo] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  const max = kind === 'DEPOSIT' ? treasury.deposit_available : MAX_AMOUNT
  const invalid =
    amount > max
      ? kind === 'DEPOSIT'
        ? `입금은 ${won(treasury.deposit_available)}까지 신청할 수 있어요 (금고 현금 − 결정 대기 입금).`
        : `한 번에 ${won(MAX_AMOUNT)}까지 신청할 수 있어요.`
      : null
  const disabledReason = !treasury.interbank_enabled
    ? '허브 연결 설정이 없어 신청할 수 없어요.'
    : kind === 'DEPOSIT' && treasury.deposit_available <= 0
      ? '입금 신청할 수 있는 금고 현금이 없어요. 고객 계좌의 가상 입금으로 금고 현금을 채울 수 있어요.'
      : null
  const flow = kind === 'DEPOSIT' ? '금고 현금 → 허브 예치금' : '허브 예치금 → 금고 현금'

  function next(event: FormEvent) {
    event.preventDefault()
    if (amount <= 0 || invalid || disabledReason) return
    setResult(null)
    setConfirming(true)
  }

  async function send() {
    setSending(true)
    try {
      const created = await adminApi.createReserveRequest({ kind, amount, memo: memo.trim() })
      if (created.status === 'FAILED') {
        setResult({ tone: 'error', text: `허브가 신청 #${created.request_id}을 받지 않았어요: ${created.reject_reason ?? '사유 없음'}` })
      } else if (created.status === 'SENDING') {
        setResult({
          tone: 'caution',
          text: `신청 #${created.request_id}: 허브 응답이 없어요. 동기화가 다시 보냅니다 (‘허브와 동기화’를 눌러도 돼요).`,
        })
      } else {
        setResult({
          tone: 'success',
          text: `신청 #${created.request_id}을 보냈어요. 허브 관리자가 승인한 뒤 ‘허브와 동기화’를 누르면 잔액에 반영돼요.`,
        })
      }
      if (created.status !== 'FAILED') {
        setAmount(0)
        setMemo('')
      }
      setConfirming(false)
      onDone()
    } catch (e) {
      if (isAdminRevoked(e)) return onRevoked()
      setResult({ tone: 'error', text: adminErrorMessage(e, '신청하지 못했어요.') })
      setConfirming(false)
      onDone() // 실패도 감사 로그에 남는다
    } finally {
      setSending(false)
    }
  }

  if (confirming)
    return (
      <div className="section-card reserve-confirm" role="group" aria-label="신청 확인">
        <p>
          <strong>{flow}</strong>으로 <strong>{won(amount)}</strong> {RESERVE_KIND_LABEL[kind]}을 신청합니다.
        </p>
        <p className="muted small">허브 관리자가 승인해야 반영됩니다. 승인 전에는 이 화면에서 취소할 수 있어요.</p>
        {memo.trim() && <p className="muted small">메모: {memo.trim()}</p>}
        <div className="button-row">
          <button type="button" className="button" onClick={() => setConfirming(false)} disabled={sending}>
            돌아가기
          </button>
          <button type="button" className="button primary" onClick={() => void send()} disabled={sending}>
            {sending ? '보내는 중…' : '신청 보내기'}
          </button>
        </div>
      </div>
    )

  return (
    <form className="form section-card reserve-form" onSubmit={next}>
      <div className="segmented" role="radiogroup" aria-label="신청 종류">
        {(['DEPOSIT', 'WITHDRAW'] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={kind === k}
            className={`segmented-item ${kind === k ? 'on' : ''}`}
            onClick={() => setKind(k)}
          >
            {k === 'DEPOSIT' ? '입금 (금고 → 허브)' : '인출 (허브 → 금고)'}
          </button>
        ))}
      </div>
      <label>
        금액 (원)
        <input
          inputMode="numeric"
          value={amount ? amount.toLocaleString('ko-KR') : ''}
          placeholder="0"
          onChange={(e) => setAmount(Math.min(Number(e.target.value.replace(/\D/g, '')) || 0, MAX_AMOUNT * 10))}
        />
        <span className="muted small">
          {[koreanWon(amount), kind === 'DEPOSIT' && `최대 ${won(treasury.deposit_available)}`].filter(Boolean).join(' · ') ||
            ' '}
        </span>
      </label>
      {kind === 'DEPOSIT' && treasury.deposit_available > 0 && (
        <button type="button" className="button small max-button" onClick={() => setAmount(treasury.deposit_available)}>
          최대 금액 넣기
        </button>
      )}
      {kind === 'WITHDRAW' && (
        <p className="muted small">인출은 허브 예치금에서 금고 현금으로 옮겨요. 허브가 예치금이 모자라면 거절해요.</p>
      )}
      <label>
        메모 (선택)
        <input value={memo} maxLength={MEMO_MAX} onChange={(e) => setMemo(e.target.value)} placeholder="예: 11월 예치" />
        <span className="muted small">
          {memo.length}/{MEMO_MAX}
        </span>
      </label>
      {invalid && <p className="error small">{invalid}</p>}
      {disabledReason && <p className="caution-note small">{disabledReason}</p>}
      {result && (
        <p className={`reserve-result ${result.tone}`} role={result.tone === 'error' ? 'alert' : 'status'}>
          {result.text}
        </p>
      )}
      <button className="button primary" disabled={amount <= 0 || !!invalid || !!disabledReason}>
        다음
      </button>
    </form>
  )
}
