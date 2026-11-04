import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { transferApi, voiceApi } from '../api/endpoints'
import type { FdsExtra, TransferConfirmationCard, TransferResult } from '../api/types'
import { useRecorder } from '../hooks/useRecorder'
import type { Speech } from '../hooks/useSpeech'
import { deviceFingerprint } from '../lib/fingerprint'
import { won } from '../lib/format'
import FdsAlert from './FdsAlert'

type Status =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: 'voice_listening' }
  | { kind: 'voice_checking' }
  | { kind: 'need_pin'; extra: FdsExtra | null; error?: string }
  | { kind: 'done'; result: TransferResult }
  | { kind: 'blocked'; extra: FdsExtra }
  | { kind: 'cancelled' }
  | { kind: 'error'; message: string }

interface Props {
  card: TransferConfirmationCard
  sessionId: string
  inputMode: 'text' | 'voice'
  active: boolean // 가장 최근 카드만 승인할 수 있다
  autoVoice: boolean // 카드 안내를 다 읽은 직후: 음성 승인 녹음을 바로 시작
  speech: Speech
  onCancel: () => void
}

const VOICE_RECORD_MS = 5000

/**
 * 이체 확인 카드. 승인하면 카드 내용과 승인 토큰 그대로 POST /transfers.
 * 목소리를 등록한 사용자는 "확인 + 숫자"를 말해 승인하고(POST /voice/approvals), 실패하면 PIN으로 승인한다.
 */
export default function TransferCard({ card, sessionId, inputMode, active, autoVoice, speech, onCancel }: Props) {
  const recorder = useRecorder()
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [pin, setPin] = useState('')
  const [voiceNote, setVoiceNote] = useState<string | null>(null)
  const [pinMode, setPinMode] = useState(false) // 목소리 등록 사용자가 버튼 + PIN으로 승인
  const voiceTokenRef = useRef<string | undefined>(undefined)
  const autoStartedRef = useRef(false)
  const [expired] = useState(() => new Date(card.expires_at).getTime() < Date.now()) // 만료 후 승인은 서버가 거절한다
  const who = card.recipient_nickname ? `${card.recipient_nickname}(${card.holder_name})` : card.holder_name
  const voiceReady = card.voice_enrolled && !!card.voice_challenge && recorder.supported && !pinMode

  async function approve(withPin?: string) {
    setStatus({ kind: 'sending' })
    try {
      const result = await transferApi.transfer({
        from_checking_account_id: card.from_checking_account_id,
        to_account_num: card.to_account_num,
        amount: card.amount,
        session_id: sessionId,
        confirmation_token: card.confirmation_token,
        voice_approval_token: voiceTokenRef.current,
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
      } else if (e.code === 'ADDITIONAL_AUTH_REQUIRED' && extra) {
        setStatus({ kind: 'need_pin', extra })
        setPin('')
        speech.speak('평소와 다른 이체예요. 이체 PIN 여섯 자리를 입력해 주세요.', { force: true })
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
  }

  async function approveByVoice() {
    if (recorder.recording) {
      recorder.stop()
      return
    }
    speech.cancelSpeech()
    setVoiceNote(null)
    setStatus({ kind: 'voice_listening' })
    let wav: Blob
    try {
      wav = await recorder.record(VOICE_RECORD_MS)
    } catch {
      fallBackToPin('마이크를 쓸 수 없어요. PIN으로 승인해 주세요.')
      return
    }
    setStatus({ kind: 'voice_checking' })
    try {
      const { voice_approval_token } = await voiceApi.approve(sessionId, card.confirmation_token, wav)
      voiceTokenRef.current = voice_approval_token
      await approve()
    } catch (e) {
      const remaining = (e instanceof ApiError ? (e.extra?.remaining_attempts as number | undefined) : undefined) ?? 0
      const message = e instanceof ApiError ? e.message : '목소리를 확인하지 못했어요.'
      if (e instanceof ApiError && ['VOICE_DIGITS_MISMATCH', 'VOICE_NOT_MATCHED', 'INVALID_AUDIO'].includes(e.code) && remaining > 0) {
        setStatus({ kind: 'idle' })
        setVoiceNote(`${message} (${remaining}번 더 할 수 있어요)`)
        speech.speak(`${message} 한 번 더 말씀해 주세요.`, { force: true })
      } else {
        fallBackToPin(message)
      }
    }
  }

  function fallBackToPin(message: string) {
    setPinMode(true)
    setVoiceNote(message)
    setStatus({ kind: 'need_pin', extra: null })
    speech.speak('목소리로 승인하지 못했어요. 이체 PIN 여섯 자리를 입력해 주세요.', { force: true })
  }

  function cancel() {
    recorder.stop()
    setStatus({ kind: 'cancelled' })
    onCancel()
  }

  const locked = !active || expired || ['done', 'blocked', 'cancelled'].includes(status.kind)

  // 카드 안내("…확인 사 칠 이 라고 말씀해 주세요")를 다 읽은 직후 녹음을 바로 시작한다.
  // 렌더마다 확인하되 ref로 카드당 한 번만 시작한다.
  useEffect(() => {
    if (autoVoice && voiceReady && !locked && !autoStartedRef.current) {
      autoStartedRef.current = true
      approveByVoice()
    }
  })

  const busy = ['sending', 'voice_listening', 'voice_checking'].includes(status.kind)
  const pinOnly = card.voice_enrolled && (pinMode || !voiceReady) // 목소리 등록 사용자의 버튼 승인은 PIN 필요

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

      {!locked && voiceReady && (status.kind === 'idle' || busy) && (
        <div className="voice-approve">
          <p>
            승인하려면 <strong className="challenge">"확인 {card.voice_challenge_text}"</strong>
            {' '}이라고 말씀해 주세요
          </p>
          <button
            className={`button primary wide ${status.kind === 'voice_listening' ? 'recording' : ''}`}
            onClick={approveByVoice}
            disabled={status.kind === 'voice_checking' || status.kind === 'sending' || card.insufficient_balance}
          >
            {status.kind === 'voice_listening'
              ? '⏺ 듣는 중… (다 말하면 누르기)'
              : status.kind === 'voice_checking'
                ? '목소리 확인 중…'
                : status.kind === 'sending'
                  ? '보내는 중…'
                  : '🎤 말로 승인하기'}
          </button>
          {voiceNote && <p className="error small">{voiceNote}</p>}
          {!busy && (
            <div className="button-row">
              <button className="button" onClick={cancel}>
                취소
              </button>
              <button className="button" onClick={() => fallBackToPin('PIN으로 승인해 주세요.')}>
                PIN으로 승인
              </button>
            </div>
          )}
        </div>
      )}

      {status.kind === 'need_pin' && (
        <>
          {status.extra && <FdsAlert extra={status.extra} blocked={false} />}
          {voiceNote && !status.extra && <p className="muted small">{voiceNote}</p>}
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
              <label>
                이체 PIN
                <input
                  type="password"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={6}
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                  autoFocus
                />
              </label>
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

      {/* 목소리 미등록: 승인 버튼 / 등록했지만 음성을 못 쓰면: PIN 입력으로 */}
      {!locked && !voiceReady && (status.kind === 'idle' || status.kind === 'sending') && (
        <div className="button-row">
          <button className="button" onClick={cancel} disabled={status.kind === 'sending'}>
            취소
          </button>
          <button
            className="button primary"
            onClick={() => (pinOnly ? setStatus({ kind: 'need_pin', extra: null }) : approve())}
            disabled={status.kind === 'sending' || card.insufficient_balance}
          >
            {status.kind === 'sending' ? '보내는 중…' : pinOnly ? 'PIN으로 승인' : '승인'}
          </button>
        </div>
      )}
    </div>
  )
}
