import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { accountApi } from '../api/endpoints'
import type { AccountDetail } from '../api/types'
import { won } from '../lib/format'
import PinPad from './PinPad'

const MAX_LIMIT = 100_000_000 // 백엔드 MAX_TRANSFER_LIMIT

interface Props {
  account: AccountDetail
  onSaved: (account: AccountDetail) => void
}

const toNumber = (text: string) => Number(text.replace(/\D/g, '')) || 0

/**
 * 입출금 계좌 이체 한도 변경. 낮추기는 바로, 높이기는 이체 PIN을 확인한다.
 * (대화로는 낮추기만 되고, 높이기는 이 화면에서만 할 수 있다)
 */
export default function TransferLimitForm({ account, onSaved }: Props) {
  const [editing, setEditing] = useState(false)
  const [perText, setPerText] = useState(String(account.per_transfer_limit ?? 0))
  const [dailyText, setDailyText] = useState(String(account.daily_transfer_limit ?? 0))
  const [pin, setPin] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<{ code: string; message: string } | null>(null)

  const per = toNumber(perText)
  const daily = toNumber(dailyText)
  const raising = per > (account.per_transfer_limit ?? 0) || daily > (account.daily_transfer_limit ?? 0)
  const invalid =
    per <= 0 || daily <= 0 || per > MAX_LIMIT || daily > MAX_LIMIT
      ? `한도는 1원 이상 ${won(MAX_LIMIT)} 이하로 정해 주세요.`
      : per > daily
        ? '1회 한도는 1일 한도보다 클 수 없어요.'
        : null

  function reset() {
    setEditing(false)
    setPerText(String(account.per_transfer_limit ?? 0))
    setDailyText(String(account.daily_transfer_limit ?? 0))
    setPin('')
    setError(null)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (invalid || (raising && pin.length !== 6)) return
    setSaving(true)
    setError(null)
    try {
      const saved = await accountApi.update('checking', account.account_id, {
        per_transfer_limit: per,
        daily_transfer_limit: daily,
        ...(raising ? { pin } : {}),
      })
      onSaved(saved)
      setEditing(false)
      setPin('')
    } catch (e) {
      setError(e instanceof ApiError ? { code: e.code, message: e.message } : { code: '', message: '바꾸지 못했어요.' })
      setPin('')
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <button className="button small" onClick={() => setEditing(true)}>
        이체 한도 바꾸기
      </button>
    )
  }

  return (
    <form className="form limit-form" onSubmit={submit}>
      <label>
        1회 이체 한도 (원)
        <input inputMode="numeric" value={perText} onChange={(e) => setPerText(e.target.value.replace(/\D/g, ''))} />
        <span className="muted small">{won(per)}</span>
      </label>
      <label>
        1일 이체 한도 (원)
        <input inputMode="numeric" value={dailyText} onChange={(e) => setDailyText(e.target.value.replace(/\D/g, ''))} />
        <span className="muted small">{won(daily)}</span>
      </label>
      {invalid && <p className="error small">{invalid}</p>}
      {raising && !invalid && (
        <div className="limit-pin">
          <span className="muted small">한도를 높이려면 본인 확인이 필요해요. 누가 전화로 한도를 올리라고 했다면 멈추세요.</span>
          <PinPad value={pin} onChange={setPin} />
        </div>
      )}
      {error && (
        <p className="error small" role="alert">
          {error.message}
          {error.code === 'PIN_NOT_SET' && (
            <>
              {' '}
              <Link to="/settings">설정에서 PIN 등록</Link>
            </>
          )}
        </p>
      )}
      <div className="button-row">
        <button type="button" className="button" onClick={reset} disabled={saving}>
          취소
        </button>
        <button className="button primary" disabled={saving || !!invalid || (raising && pin.length !== 6)}>
          {saving ? '바꾸는 중…' : raising ? 'PIN 확인 후 바꾸기' : '바꾸기'}
        </button>
      </div>
    </form>
  )
}
