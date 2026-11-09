import { useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import { accountApi } from '../api/endpoints'
import type { AccountDetail } from '../api/types'
import { won } from '../lib/format'

const MAX_AMOUNT = 1_000_000 // 백엔드 CASH_DEPOSIT_MAX_AMOUNT 기본값
const QUICK_AMOUNTS = [10_000, 50_000, 100_000, 500_000]

interface Props {
  account: AccountDetail
  onDone: () => void // 입금 뒤 계좌·거래내역을 다시 불러온다
  onCancel: () => void
}

const toNumber = (text: string) => Number(text.replace(/\D/g, '')) || 0

/** 시연용 가상 입금 (현금 입금 흉내). 1회 100만원, 하루 300만원까지 (서버가 최종 확인) */
export default function CashDepositForm({ account, onDone, onCancel }: Props) {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const amount = toNumber(text)
  const invalid = amount > MAX_AMOUNT ? `한 번에 ${won(MAX_AMOUNT)}까지 입금할 수 있어요.` : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (amount <= 0 || invalid) return
    setSaving(true)
    setError(null)
    try {
      await accountApi.cashDeposit(account.account_id, amount)
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '입금하지 못했어요.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="form limit-form" onSubmit={submit}>
      <p className="muted small">
        시연용 가상 입금이에요. 실제 돈은 오가지 않고, 이 계좌 잔액만 늘어나요. 1회 100만원, 하루 300만원까지.
      </p>
      <label>
        입금할 금액 (원)
        <input
          inputMode="numeric"
          autoFocus
          value={text}
          placeholder="0"
          onChange={(e) => setText(e.target.value.replace(/\D/g, ''))}
        />
        <span className="muted small">{won(amount)}</span>
      </label>
      <div className="button-row">
        {QUICK_AMOUNTS.map((quick) => (
          <button key={quick} type="button" className="button small" onClick={() => setText(String(amount + quick))}>
            +{quick >= 10_000 ? `${quick / 10_000}만` : quick}
          </button>
        ))}
      </div>
      {invalid && <p className="error small">{invalid}</p>}
      {error && (
        <p className="error small" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button type="button" className="button" onClick={onCancel} disabled={saving}>
          취소
        </button>
        <button className="button primary" disabled={saving || amount <= 0 || !!invalid}>
          {saving ? '입금하는 중…' : `${won(amount)} 입금하기`}
        </button>
      </div>
    </form>
  )
}
