import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '../api/client'
import { accountApi, transferApi } from '../api/endpoints'
import type { AccountSummary, Bank, FdsExtra, HolderInquiryResult, InterbankTransfer, OwnAccount, TransferResult } from '../api/types'
import FdsAlert from '../components/FdsAlert'
import OwnAccountsPanel from '../components/OwnAccountsPanel'
import { useLoad } from '../hooks/useLoad'
import { deviceFingerprint } from '../lib/fingerprint'
import { dateTime, won } from '../lib/format'

const OWN_BANK = '' // 우리 은행 (to_bank를 보내지 않는다)
const QUICK_AMOUNTS = [10_000, 50_000, 100_000]

type Step =
  | { kind: 'form'; error?: string }
  | { kind: 'checking' } // 받는 분 확인 중
  | { kind: 'confirm'; holder: HolderInquiryResult }
  | { kind: 'sending'; holder: HolderInquiryResult }
  | { kind: 'need_pin'; holder: HolderInquiryResult; extra: FdsExtra | null; error?: string }
  | { kind: 'blocked'; holder: HolderInquiryResult; extra: FdsExtra }
  | { kind: 'done'; holder: HolderInquiryResult; result: TransferResult }
  | { kind: 'refunded'; holder: HolderInquiryResult; message: string; balanceAfter: number | null }
  | { kind: 'failed'; holder: HolderInquiryResult; message: string }

const INTERBANK_STATUS_LABEL: Record<InterbankTransfer['status'], string> = {
  PENDING: '확인 중',
  COMPLETED: '완료',
  FAILED: '돌려받음',
}

/**
 * 이체 화면 (모아 없이 직접). 우리 은행과 ClearingHub에 참가한 다른 은행으로 보낼 수 있다.
 * 입력 → 받는 분 이름 확인 → 보내기. FDS가 PIN을 요구하면 PIN, 차단하면 경고를 보여 준다.
 */
export default function TransferPage() {
  const [params] = useSearchParams()
  // 보낸 뒤 잔액을 다시 불러와도 화면이 깜빡이지 않도록 마지막 목록을 들고 있는다
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null)
  const [accountsError, setAccountsError] = useState<string | null>(null)
  const refreshAccounts = useCallback(() => {
    accountApi.list().then(setAccounts, (e) => setAccountsError(e instanceof ApiError ? e.message : '계좌를 불러오지 못했어요.'))
  }, [])
  const [banks, setBanks] = useState<Bank[] | null>(null) // null: 불러오는 중
  const [banksUnavailable, setBanksUnavailable] = useState(false)
  const [historyRound, setHistoryRound] = useState(0)
  const { data: history } = useLoad(useCallback(() => transferApi.interbank(), [historyRound])) // eslint-disable-line react-hooks/exhaustive-deps

  const checking = (accounts ?? []).filter((a) => a.account_type === 'checking')
  const [fromId, setFromId] = useState(params.get('from') ?? '')
  const [toBank, setToBank] = useState(OWN_BANK)
  const [toAccount, setToAccount] = useState('')
  const [amount, setAmount] = useState('')
  const [pin, setPin] = useState('')
  const [step, setStep] = useState<Step>({ kind: 'form' })
  // 다른 은행 내 계좌를 골랐으면 계좌번호 대신 허브 참조값으로 보낸다 (번호는 가려진 채로 보여 준다)
  const [ownAccount, setOwnAccount] = useState<OwnAccount | null>(null)
  const [ownPanelOpen, setOwnPanelOpen] = useState(false)

  const source: AccountSummary | undefined = checking.find((a) => String(a.account_id) === fromId) ?? checking[0]
  const amountValue = Number(amount)
  const canCheck = !!source && toAccount.trim().length > 0 && amountValue > 0 && step.kind === 'form'

  useEffect(refreshAccounts, [refreshAccounts])

  useEffect(() => {
    let alive = true
    transferApi.banks().then(
      (list) => alive && setBanks(list),
      () => {
        if (!alive) return
        setBanks([])
        setBanksUnavailable(true) // 허브 설정이 없거나 응답 없음: 우리 은행으로만 보낼 수 있다
      },
    )
    return () => {
      alive = false
    }
  }, [])

  async function checkHolder() {
    if (!source) return
    if (amountValue > source.balance) {
      setStep({ kind: 'form', error: '출금 계좌 잔액이 부족해요.' })
      return
    }
    if (ownAccount) {
      // 허브가 같은 사람(가상 CI)의 계좌로 확인해 준 것이라 받는 분 조회를 따로 하지 않는다
      setStep({ kind: 'confirm', holder: {
        to_bank: ownAccount.bank_code, bank_name: ownAccount.bank_name,
        to_account_num: ownAccount.account_masked, holder_name: '본인 (내 계좌)',
      } })
      return
    }
    setStep({ kind: 'checking' })
    try {
      const holder = await transferApi.inquiry({ to_bank: toBank || undefined, to_account_num: toAccount.trim() })
      setStep({ kind: 'confirm', holder })
    } catch (e) {
      setStep({ kind: 'form', error: e instanceof ApiError ? e.message : '받는 분을 확인하지 못했어요.' })
    }
  }

  async function send(holder: HolderInquiryResult, withPin?: string) {
    if (!source) return
    setStep({ kind: 'sending', holder })
    try {
      const result = await transferApi.transfer({
        from_checking_account_id: source.account_id,
        to_bank: toBank || undefined,
        to_account_num: holder.to_account_num,
        to_account_ref: ownAccount?.account_ref,
        amount: amountValue,
        pin: withPin,
        device_fingerprint: await deviceFingerprint(),
      })
      setStep({ kind: 'done', holder, result })
      refreshAccounts()
      if (toBank) setHistoryRound((n) => n + 1)
    } catch (e) {
      handleError(holder, e)
    }
  }

  function handleError(holder: HolderInquiryResult, e: unknown) {
    if (!(e instanceof ApiError)) {
      setStep({ kind: 'failed', holder, message: '이체하지 못했어요.' })
      return
    }
    const extra = e.extra as FdsExtra | null
    if (e.code === 'FDS_BLOCKED' && extra) {
      setStep({ kind: 'blocked', holder, extra })
    } else if (e.code === 'ADDITIONAL_AUTH_REQUIRED' && extra) {
      setPin('')
      setStep({ kind: 'need_pin', holder, extra })
    } else if (e.code === 'INVALID_PIN') {
      setPin('')
      setStep((prev) => ({ kind: 'need_pin', holder, extra: prev.kind === 'need_pin' ? prev.extra : null, error: e.message }))
    } else if (e.code === 'INTERBANK_FAILED') {
      setStep({ kind: 'refunded', holder, message: e.message, balanceAfter: (e.extra?.balance_after as number | undefined) ?? null })
      refreshAccounts()
      setHistoryRound((n) => n + 1)
    } else {
      setStep({ kind: 'failed', holder, message: e.message })
    }
  }

  function pickOwnAccount(account: OwnAccount) {
    setToBank(account.bank_code)
    setToAccount(account.account_masked)
    setOwnAccount(account)
    setOwnPanelOpen(false)
  }

  function clearOwnAccount() {
    setOwnAccount(null)
    setToAccount('')
  }

  function reset() {
    setOwnAccount(null)
    setToAccount('')
    setAmount('')
    setPin('')
    setStep({ kind: 'form' })
  }

  const bankName = (code: string) => banks?.find((b) => b.bank_code === code)?.name ?? code

  return (
    <section className="page transfer-page">
      <Link to="/accounts" className="back">
        ← 내 계좌
      </Link>
      <h1>이체</h1>
      {accountsError && <p className="error">{accountsError}</p>}
      {accounts && checking.length === 0 && (
        <p className="muted">
          보낼 입출금 계좌가 없어요. <Link to="/products?kind=account">계좌 만들기</Link>
        </p>
      )}

      {source && (step.kind === 'form' || step.kind === 'checking') && (
        <form
          className="form transfer-form"
          onSubmit={(e) => {
            e.preventDefault()
            if (canCheck) checkHolder()
          }}
        >
          <label>
            출금 계좌
            <select value={String(source.account_id)} onChange={(e) => setFromId(e.target.value)}>
              {checking.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.nickname ?? '입출금 계좌'} ({a.account_num.slice(-4)}) · {won(a.balance)}
                </option>
              ))}
            </select>
          </label>
          <label>
            받는 은행
            <select
              value={toBank}
              onChange={(e) => {
                setToBank(e.target.value)
                if (ownAccount) clearOwnAccount()
              }}
              disabled={banks === null}
            >
              <option value={OWN_BANK}>AvengersBank (우리 은행)</option>
              {(banks ?? []).map((b) => (
                <option key={b.bank_code} value={b.bank_code}>
                  {b.name}
                </option>
              ))}
            </select>
            {banksUnavailable && <span className="muted small">지금은 다른 은행으로 보낼 수 없어요. 우리 은행 계좌로만 보낼 수 있어요.</span>}
          </label>
          <label>
            받는 계좌번호
            <input
              inputMode="numeric"
              autoComplete="off"
              placeholder="110-123-456789"
              maxLength={20}
              value={toAccount}
              readOnly={!!ownAccount}
              onChange={(e) => setToAccount(e.target.value.replace(/[^\d-]/g, ''))}
            />
            {ownAccount ? (
              <span className="muted small">
                내 계좌 · {ownAccount.product_name || '입출금 계좌'}{' '}
                <button type="button" className="button link small" onClick={clearOwnAccount}>
                  다른 계좌 입력
                </button>
              </span>
            ) : (
              !banksUnavailable &&
              (banks ?? []).length > 0 && (
                <button type="button" className="button small own-accounts-open" onClick={() => setOwnPanelOpen(true)}>
                  다른 은행 내 계좌 불러오기
                </button>
              )
            )}
          </label>
          {ownPanelOpen && <OwnAccountsPanel bankName={bankName} onPick={pickOwnAccount} onClose={() => setOwnPanelOpen(false)} />}
          <label>
            금액
            <input
              inputMode="numeric"
              autoComplete="off"
              placeholder="0"
              value={amount ? Number(amount).toLocaleString('ko-KR') : ''}
              onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').slice(0, 12))}
            />
            <span className="quick-amounts">
              {QUICK_AMOUNTS.map((q) => (
                <button key={q} type="button" className="button small" onClick={() => setAmount(String(amountValue + q))}>
                  +{q / 10_000}만
                </button>
              ))}
              <button type="button" className="button small" onClick={() => setAmount(String(source.balance))}>
                전액
              </button>
            </span>
          </label>
          {step.kind === 'form' && step.error && <p className="error">{step.error}</p>}
          <button className="button primary" disabled={!canCheck}>
            {step.kind === 'checking' ? '받는 분 확인 중…' : '다음'}
          </button>
        </form>
      )}

      {source && 'holder' in step && (
        <div className={`chat-card transfer-card status-${step.kind}`}>
          <p className="chat-card-title">이체 확인</p>
          <dl className="transfer-facts">
            <dt>받는 분</dt>
            <dd>{step.holder.holder_name}</dd>
            <dt>받는 계좌</dt>
            <dd>
              {step.holder.bank_name} {step.holder.to_account_num}
            </dd>
            <dt>금액</dt>
            <dd className="transfer-amount">{won(amountValue)}</dd>
            <dt>출금 계좌</dt>
            <dd>
              {source.nickname ?? '입출금'} ({source.account_num.slice(-4)})
            </dd>
          </dl>

          {(step.kind === 'confirm' || step.kind === 'sending') && (
            <>
              <p className="small">받는 분 이름이 맞는지 꼭 확인하세요. 모르는 사람이 시켜서 보내는 돈이라면 보내지 마세요.</p>
              <div className="button-row">
                <button className="button" onClick={() => setStep({ kind: 'form' })} disabled={step.kind === 'sending'}>
                  고치기
                </button>
                <button className="button primary" onClick={() => send(step.holder)} disabled={step.kind === 'sending'}>
                  {step.kind === 'sending' ? '보내는 중…' : '보내기'}
                </button>
              </div>
            </>
          )}

          {step.kind === 'need_pin' && (
            <>
              {step.extra && <FdsAlert extra={step.extra} blocked={false} />}
              {step.extra?.has_pin === false ? (
                <p className="small">
                  아직 이체 PIN이 없어요. <Link to="/settings">설정에서 PIN 등록</Link> 후 다시 보내 주세요.
                </p>
              ) : (
                <form
                  className="pin-form"
                  onSubmit={(e) => {
                    e.preventDefault()
                    send(step.holder, pin)
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
                  {step.error && <p className="error small">{step.error}</p>}
                  <button className="button primary" disabled={pin.length !== 6}>
                    PIN 확인 후 보내기
                  </button>
                </form>
              )}
              <button className="button link" onClick={reset}>
                이체 취소
              </button>
            </>
          )}

          {step.kind === 'blocked' && <FdsAlert extra={step.extra} blocked />}

          {step.kind === 'done' && step.result.status === 'PENDING' && (
            <p className="caution-note">
              ⏳ 돈은 출금됐고, {step.holder.bank_name}에서 받았는지 확인하고 있어요. 확인되면 아래 "다른 은행 이체"에
              완료로 바뀌어요. 받는 은행이 거절하면 돈을 돌려드려요.
            </p>
          )}
          {step.kind === 'done' && step.result.status !== 'PENDING' && (
            <p className="success">
              ✅ 보냈어요. 남은 잔액 <strong>{won(step.result.balance_after)}</strong>
            </p>
          )}
          {step.kind === 'refunded' && (
            <p className="error">
              {step.message}
              {step.balanceAfter != null && <> 남은 잔액 {won(step.balanceAfter)}</>}
            </p>
          )}
          {step.kind === 'failed' && <p className="error">{step.message}</p>}

          {['done', 'blocked', 'refunded', 'failed'].includes(step.kind) && (
            <div className="button-row">
              <Link className="button" to={`/accounts/checking/${source.account_id}`}>
                거래내역 보기
              </Link>
              <button className="button primary" onClick={reset}>
                새로 보내기
              </button>
            </div>
          )}
        </div>
      )}

      {history && history.length > 0 && (
        <>
          <h2>
            다른 은행 이체{' '}
            <button className="button small" onClick={() => setHistoryRound((n) => n + 1)}>
              새로고침
            </button>
          </h2>
          <ul className="list">
            {history.map((t) => (
              <li key={t.transfer_id} className="list-item static">
                <span>
                  <span className={`badge interbank-${t.status.toLowerCase()}`}>{INTERBANK_STATUS_LABEL[t.status]}</span>
                  <strong>
                    {t.to_holder_name ?? t.to_account} · {bankName(t.to_bank)}
                  </strong>
                  <span className="muted small">
                    {dateTime(t.created_at)}
                    {t.status === 'FAILED' && t.fail_message ? ` · ${t.fail_message}` : ''}
                  </span>
                </span>
                <span className={`amount ${t.status === 'FAILED' ? '' : 'minus'}`}>{won(t.amount)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
