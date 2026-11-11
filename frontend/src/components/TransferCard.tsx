import { useEffect, useRef, useState } from 'react'
import { CircleCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ApiError, newIdempotencyKey } from '../api/client'
import PinPad from './PinPad'
import { transferApi } from '../api/endpoints'
import type { FdsExtra, TransferConfirmationCard, TransferResult } from '../api/types'
import { deviceFingerprint } from '../lib/fingerprint'
import { won } from '../lib/format'
import FdsAlert from './FdsAlert'

export type Status =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: 'need_pin'; extra: FdsExtra | null; error?: string }
  | { kind: 'done'; result: TransferResult }
  | { kind: 'blocked'; extra: FdsExtra }
  | { kind: 'cancelled' }
  | { kind: 'error'; message: string }

interface Props {
  card: TransferConfirmationCard
  sessionId: string
  active: boolean // 가장 최근 카드만 승인할 수 있다
  onCancel: () => void
  onStatusChange?: (kind: Status['kind']) => void // 도우미 화면이 캐릭터 표정을 바꾼다
}

/** 이체 확인 카드. 승인하면 카드 내용과 승인 토큰 그대로 POST /transfers. FDS가 요구하면 PIN을 받는다. */
export default function TransferCard({ card, sessionId, active, onCancel, onStatusChange }: Props) {
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [pin, setPin] = useState('')
  const idempotencyKeyRef = useRef(newIdempotencyKey()) // 카드 하나 = 이체 하나. PIN 재시도도 같은 키
  const [expired] = useState(() => new Date(card.expires_at).getTime() < Date.now()) // 만료 후 승인은 서버가 거절한다
  const who =
    card.to_label ??
    (card.recipient_nickname
      ? `${card.recipient_nickname}(${card.holder_name})`
      : card.to_bank_name
        ? `${card.to_bank_name} ${card.holder_name}`
        : card.holder_name)

  async function approve(withPin?: string) {
    setStatus({ kind: 'sending' })
    try {
      setStatus({ kind: 'done', result: await send(withPin) })
    } catch (e) {
      handleError(e)
    }
  }

  /** 내 적금·예금으로 넣기는 납입 API, 그 밖(남에게, 내 입출금 계좌로)은 확인 토큰을 실은 이체 */
  async function send(withPin?: string) {
    if (card.destination_type === 'savings' && card.to_account_id) {
      return transferApi.paySavings({
        from_checking_account_id: card.from_checking_account_id,
        savings_account_id: card.to_account_id,
        amount: card.amount,
      })
    }
    if (card.destination_type === 'deposit' && card.to_account_id) {
      return transferApi.payDeposit({
        from_checking_account_id: card.from_checking_account_id,
        deposit_account_id: card.to_account_id,
        amount: card.amount,
      })
    }
    return transferApi.transfer({
      from_checking_account_id: card.from_checking_account_id,
      to_bank: card.to_bank ?? undefined,
      to_account_num: card.to_account_num,
      amount: card.amount,
      session_id: sessionId,
      confirmation_token: card.confirmation_token,
      pin: withPin,
      device_fingerprint: await deviceFingerprint(),
    }, idempotencyKeyRef.current)
  }

  function handleError(e: unknown) {
    if (!(e instanceof ApiError)) {
      setStatus({ kind: 'error', message: '이체하지 못했어요.' })
      return
    }
    const extra = e.extra as FdsExtra | null
    if (e.code === 'FDS_BLOCKED' && extra) {
      setStatus({ kind: 'blocked', extra })
    } else if (e.code === 'ADDITIONAL_AUTH_REQUIRED' && extra) {
      setStatus({ kind: 'need_pin', extra })
      setPin('')
    } else if (e.code === 'PIN_REQUIRED' || e.code === 'INVALID_PIN') {
      setStatus((prev) => ({
        kind: 'need_pin',
        extra: extra?.rule_hits ? extra : prev.kind === 'need_pin' ? prev.extra : null,
        error: e.code === 'INVALID_PIN' ? e.message : undefined,
      }))
      setPin('')
    } else {
      setStatus({ kind: 'error', message: e.message })
    }
  }

  function cancel() {
    setStatus({ kind: 'cancelled' })
    onCancel()
  }

  useEffect(() => {
    onStatusChange?.(status.kind)
  }, [status.kind, onStatusChange])

  const locked = !active || expired || ['done', 'blocked', 'cancelled'].includes(status.kind)

  return (
    <div className={`chat-card transfer-card status-${status.kind}`}>
      <p className="chat-card-title">이체 확인</p>
      <dl className="transfer-facts">
        <dt>받는 분</dt>
        <dd>{who}</dd>
        <dt>금액</dt>
        <dd className="transfer-amount">{won(card.amount)}</dd>
        <dt>출금 계좌</dt>
        <dd>
          {card.from_nickname ?? '입출금'} <span className="muted small">잔액 {won(card.from_balance)}</span>
        </dd>
      </dl>
      {card.insufficient_balance && <p className="error small">출금 계좌 잔액이 부족해요.</p>}

      {status.kind === 'need_pin' && (
        <>
          {status.extra && <FdsAlert extra={status.extra} blocked={false} />}
          {status.extra?.has_pin === false ? (
            <p className="small">
              아직 이체 PIN이 없어요. <Link to="/settings">설정에서 PIN 등록</Link> 후 다시 승인해 주세요.
            </p>
          ) : (
            <form
              className="pin-form"
              onSubmit={(e) => {
                e.preventDefault()
                approve(pin)
              }}
            >
              <PinPad value={pin} onChange={setPin} autoFocus />
              {status.error && <p className="error small">{status.error}</p>}
              <button className="button primary" disabled={pin.length !== 6}>
                PIN 확인 후 보내기
              </button>
            </form>
          )}
          <button className="button link" onClick={cancel}>
            이체 취소
          </button>
        </>
      )}
      {status.kind === 'blocked' && <FdsAlert extra={status.extra} blocked />}
      {status.kind === 'done' && status.result.status === 'PENDING' && (
        <p className="caution-note">
          ⏳ 출금됐고, {card.to_bank_name ?? '받는 은행'}에서 받았는지 확인하고 있어요. 결과는{' '}
          <Link to="/transfer">이체 화면</Link>의 "다른 은행 이체"에서 볼 수 있어요. 거절되면 돈을 돌려드려요.
        </p>
      )}
      {status.kind === 'done' && status.result.status !== 'PENDING' && (
        <p className="success">
          <CircleCheck size={20} aria-hidden="true" /> 보냈어요. 남은 잔액 <strong>{won(status.result.balance_after)}</strong>
        </p>
      )}
      {status.kind === 'cancelled' && <p className="muted">취소했어요.</p>}
      {status.kind === 'error' && <p className="error">{status.message}</p>}
      {!active && status.kind === 'idle' && <p className="muted small">지난 확인 카드예요.</p>}
      {active && expired && status.kind === 'idle' && (
        <p className="muted small">확인 시간이 지났어요. 다시 말씀해 주세요.</p>
      )}

      {!locked && (status.kind === 'idle' || status.kind === 'sending') && (
        <div className="button-row">
          <button className="button" onClick={cancel} disabled={status.kind === 'sending'}>
            취소
          </button>
          <button
            className="button primary"
            onClick={() => approve()}
            disabled={status.kind === 'sending' || card.insufficient_balance}
          >
            {status.kind === 'sending' ? '보내는 중…' : '승인'}
          </button>
        </div>
      )}
    </div>
  )
}
