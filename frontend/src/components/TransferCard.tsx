import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { transferApi } from '../api/endpoints'
import type { FdsExtra, TransferConfirmationCard, TransferResult } from '../api/types'
import type { Speech } from '../hooks/useSpeech'
import { deviceFingerprint } from '../lib/fingerprint'
import { won } from '../lib/format'
import FdsAlert from './FdsAlert'

type Status =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: 'need_pin'; extra: FdsExtra; error?: string }
  | { kind: 'done'; result: TransferResult }
  | { kind: 'blocked'; extra: FdsExtra }
  | { kind: 'cancelled' }
  | { kind: 'error'; message: string }

interface Props {
  card: TransferConfirmationCard
  sessionId: string
  inputMode: 'text' | 'voice'
  active: boolean // 가장 최근 카드만 승인할 수 있다
  speech: Speech
  onCancel: () => void
}

/** 이체 확인 카드: 승인하면 카드 내용과 승인 토큰 그대로 POST /transfers. 결과에 따라 PIN 입력·차단 안내. */
export default function TransferCard({ card, sessionId, inputMode, active, speech, onCancel }: Props) {
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [pin, setPin] = useState('')
  const [expired] = useState(() => new Date(card.expires_at).getTime() < Date.now()) // 만료 후 승인은 서버가 거절한다
  const who = card.recipient_nickname ? `${card.recipient_nickname}(${card.holder_name})` : card.holder_name

  async function approve(withPin?: string) {
    setStatus({ kind: 'sending' })
    try {
      const result = await transferApi.transfer({
        from_checking_account_id: card.from_checking_account_id,
        to_account_num: card.to_account_num,
        amount: card.amount,
        session_id: sessionId,
        confirmation_token: card.confirmation_token,
        pin: withPin,
        device_fingerprint: await deviceFingerprint(),
        input_mode: inputMode,
      })
      setStatus({ kind: 'done', result })
      speech.speak(`이체를 완료했어요. 남은 잔액은 ${won(result.balance_after)}입니다.`)
    } catch (e) {
      if (!(e instanceof ApiError)) {
        setStatus({ kind: 'error', message: '이체하지 못했어요.' })
        return
      }
      const extra = e.extra as FdsExtra | null
      if (e.code === 'FDS_BLOCKED' && extra) {
        setStatus({ kind: 'blocked', extra })
        // 보이스피싱 피해자는 화면을 잘 안 본다: 음성 안내가 꺼져 있어도 경고는 읽는다
        speech.speak(`이체를 막았어요. ${extra.warning ?? ''}`, { force: true })
      } else if ((e.code === 'ADDITIONAL_AUTH_REQUIRED' || e.code === 'INVALID_PIN') && extra) {
        setStatus({ kind: 'need_pin', extra, error: e.code === 'INVALID_PIN' ? e.message : undefined })
        setPin('')
        if (e.code === 'ADDITIONAL_AUTH_REQUIRED') {
          speech.speak('평소와 다른 이체예요. 이체 PIN 여섯 자리를 입력해 주세요.', { force: true })
        }
      } else {
        setStatus({ kind: 'error', message: e.message })
      }
    }
  }

  function cancel() {
    setStatus({ kind: 'cancelled' })
    onCancel()
  }

  const locked = !active || expired || status.kind === 'done' || status.kind === 'blocked' || status.kind === 'cancelled'

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
          <FdsAlert extra={status.extra} blocked={false} />
          {status.extra.has_pin === false ? (
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
              <label>
                이체 PIN
                <input
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={6}
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                  aria-describedby="pin-error"
                  autoFocus
                />
              </label>
              {status.error && (
                <p id="pin-error" className="error small">
                  {status.error}
                </p>
              )}
              <button className="button primary" disabled={pin.length !== 6}>
                PIN 확인 후 보내기
              </button>
            </form>
          )}
        </>
      )}
      {status.kind === 'blocked' && <FdsAlert extra={status.extra} blocked />}
      {status.kind === 'done' && (
        <p className="success">
          ✅ 보냈어요. 남은 잔액 <strong>{won(status.result.balance_after)}</strong>
        </p>
      )}
      {status.kind === 'cancelled' && <p className="muted">취소했어요.</p>}
      {status.kind === 'error' && <p className="error">{status.message}</p>}
      {!active && status.kind === 'idle' && <p className="muted small">지난 확인 카드예요.</p>}
      {active && expired && status.kind === 'idle' && (
        <p className="muted small">확인 시간이 지났어요. 다시 말씀해 주세요.</p>
      )}

      {!locked && status.kind !== 'need_pin' && (
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
      {status.kind === 'need_pin' && (
        <button className="button link" onClick={cancel}>
          이체 취소
        </button>
      )}
    </div>
  )
}
