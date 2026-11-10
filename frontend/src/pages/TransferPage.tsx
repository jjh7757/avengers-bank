import { useCallback, useEffect, useState } from 'react'
import { Building2, ChevronLeft, CircleX, Clock, RefreshCw, ShieldAlert, Wallet } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'

import { ApiError, newIdempotencyKey } from '../api/client'
import { accountApi, transferApi } from '../api/endpoints'
import type {
  AccountSummary,
  Bank,
  FdsExtra,
  HolderInquiryResult,
  InterbankTransfer,
  OwnAccount,
  RecentRecipient,
  TransferResult,
} from '../api/types'
import FdsAlert from '../components/FdsAlert'
import OwnAccountsPanel from '../components/OwnAccountsPanel'
import PinPad from '../components/PinPad'
import { AccountIcon, EmptyState, ErrorState, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { deviceFingerprint } from '../lib/fingerprint'
import { dateTime, formatOwnAccountInput, koreanWon, won } from '../lib/format'

const OWN_BANK = '' // 우리 은행 (to_bank를 보내지 않는다)
const QUICK_AMOUNTS = [10_000, 50_000, 100_000]
const RECENT_SHOWN = 5 // 처음에 보여 줄 최근 보낸 사람 수 (더 보기로 최대 10명)

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
  // 최근 보낸 사람: 보낸 뒤에도 다시 불러 방금 보낸 사람이 맨 앞에 오게 한다 (못 불러오면 목록을 숨긴다)
  const [recentRound, setRecentRound] = useState(0)
  const { data: recent } = useLoad(useCallback(() => transferApi.recentRecipients(), [recentRound])) // eslint-disable-line react-hooks/exhaustive-deps
  const [recentAll, setRecentAll] = useState(false)

  const checking = (accounts ?? []).filter((a) => a.account_type === 'checking')
  const [fromId, setFromId] = useState(params.get('from') ?? '')
  const [toBank, setToBank] = useState(OWN_BANK)
  const [toAccount, setToAccount] = useState('')
  const [amount, setAmount] = useState('')
  const [pin, setPin] = useState('')
  const [step, setStep] = useState<Step>({ kind: 'form' })
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey)
  // 다른 은행 내 계좌를 골랐으면 계좌번호 대신 허브 참조값으로 보낸다 (번호는 가려진 채로 보여 준다)
  const [ownAccount, setOwnAccount] = useState<OwnAccount | null>(null)
  const [ownPanelOpen, setOwnPanelOpen] = useState(false)

  const source: AccountSummary | undefined = checking.find((a) => String(a.account_id) === fromId) ?? checking[0]
  const amountValue = Number(amount)
  const canCheck = !!source && toAccount.trim().length > 0 && amountValue > 0 && step.kind === 'form'

  useEffect(refreshAccounts, [refreshAccounts])

  // 확인·완료 화면으로 넘어가면 맨 위부터 보이게
  const stepKind = step.kind
  useEffect(() => {
    if (stepKind !== 'form' && stepKind !== 'checking') window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [stepKind])

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
    setIdempotencyKey(newIdempotencyKey()) // 확인 화면 하나 = 이체 하나. 보내기·PIN 재시도는 같은 키를 쓴다
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
      }, idempotencyKey)
      setStep({ kind: 'done', holder, result })
      refreshAccounts()
      setRecentRound((n) => n + 1)
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

  function pickRecent(r: RecentRecipient) {
    setOwnAccount(null)
    setToBank(r.to_bank ?? OWN_BANK)
    setToAccount(r.account_num)
    if (step.kind === 'form' && step.error) setStep({ kind: 'form' })
    document.getElementById('tf-amount')?.focus()
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
  // 다른 은행 상대는 허브 은행 목록에 있을 때만 고를 수 있다 (허브가 안 되면 우리 은행 상대만)
  const canPick = (r: RecentRecipient) => !r.to_bank || !!banks?.some((b) => b.bank_code === r.to_bank)
  const recentShown = (recent ?? []).slice(0, recentAll ? undefined : RECENT_SHOWN)

  const sentAt = step.kind === 'done' ? step.result.transferred_at : null
  const overBalance = !!source && amountValue > source.balance

  return (
    <section className="page transfer-page">
      <Link to="/accounts" className="back">
        <ChevronLeft size={18} aria-hidden="true" /> 내 계좌
      </Link>
      <h1>이체</h1>
      {accountsError && <ErrorState message={accountsError} />}
      {!accounts && !accountsError && <SkeletonList rows={3} height={96} />}
      {accounts && checking.length === 0 && (
        <EmptyState
          icon={Wallet}
          title="보낼 입출금 계좌가 없어요"
          description="입출금 통장을 만들면 바로 이체할 수 있어요."
          action={{ to: '/products?kind=account', label: '계좌 만들기' }}
        />
      )}

      {source && (step.kind === 'form' || step.kind === 'checking') && (
        <form
          className="transfer-form"
          onSubmit={(e) => {
            e.preventDefault()
            if (canCheck) checkHolder()
          }}
        >
          <div className="tf-section">
            <label className="tf-label" htmlFor="tf-from">
              출금 계좌
            </label>
            <div className="tf-from">
              <AccountIcon type="checking" />
              <select id="tf-from" value={String(source.account_id)} onChange={(e) => setFromId(e.target.value)}>
                {checking.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.nickname ?? '입출금 계좌'} ({a.account_num.slice(-4)})
                  </option>
                ))}
              </select>
            </div>
            <p className="tf-balance">
              출금 가능 <strong>{won(source.balance)}</strong>
            </p>
          </div>

          <div className="tf-section">
            <label className="tf-label" htmlFor="tf-bank">
              받는 분
            </label>
            <select
              id="tf-bank"
              value={toBank}
              onChange={(e) => {
                setToBank(e.target.value)
                if (ownAccount) clearOwnAccount()
                else if (e.target.value === OWN_BANK) setToAccount((v) => formatOwnAccountInput(v))
              }}
              disabled={banks === null}
              aria-label="받는 은행"
            >
              <option value={OWN_BANK}>AvengersBank (우리 은행)</option>
              {(banks ?? []).map((b) => (
                <option key={b.bank_code} value={b.bank_code}>
                  {b.name}
                </option>
              ))}
            </select>
            {banksUnavailable && <span className="muted small">지금은 다른 은행으로 보낼 수 없어요. 우리 은행 계좌로만 보낼 수 있어요.</span>}
            <input
              inputMode="numeric"
              autoComplete="off"
              placeholder={toBank === OWN_BANK ? '계좌번호 (숫자만 입력)' : '계좌번호 입력'}
              aria-label="받는 계좌번호"
              maxLength={20}
              value={toAccount}
              readOnly={!!ownAccount}
              // 우리 은행은 숫자만 치면 하이픈을 알아서 넣는다. 다른 은행은 번호 모양을 몰라 입력한 그대로 둔다
              onChange={(e) =>
                setToAccount(toBank === OWN_BANK ? formatOwnAccountInput(e.target.value) : e.target.value.replace(/[^\d-]/g, ''))
              }
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
                  <Building2 size={16} aria-hidden="true" /> 다른 은행 내 계좌 불러오기
                </button>
              )
            )}
          </div>
          {recentShown.length > 0 && (
            <div className="tf-section recent-recipients">
              <span className="tf-label">최근 보낸 사람</span>
              <ul>
                {recentShown.map((r) => {
                  const selected = !ownAccount && (r.to_bank ?? OWN_BANK) === toBank && r.account_num === toAccount.trim()
                  return (
                    <li key={`${r.to_bank ?? ''}:${r.account_num}`}>
                      <button
                        type="button"
                        className={`recent-recipient ${selected ? 'selected' : ''}`}
                        onClick={() => pickRecent(r)}
                        disabled={!canPick(r)}
                        aria-pressed={selected}
                      >
                        <span className="receipt-avatar small" aria-hidden="true">
                          {(r.holder_name ?? '?').slice(0, 1)}
                        </span>
                        <span className="recent-recipient-body">
                          <strong>{r.holder_name ?? '이름 모름'}</strong>
                          <span className="muted small">
                            {r.to_bank ? bankName(r.to_bank) : 'AvengersBank'} {r.account_num}
                          </span>
                        </span>
                        <span className="muted small">{dateTime(r.last_sent_at)}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
              {(recent ?? []).length > RECENT_SHOWN && (
                <button type="button" className="button link small" onClick={() => setRecentAll((v) => !v)}>
                  {recentAll ? '접기' : `더 보기 (${(recent ?? []).length - RECENT_SHOWN}명)`}
                </button>
              )}
            </div>
          )}
          {ownPanelOpen && <OwnAccountsPanel bankName={bankName} onPick={pickOwnAccount} onClose={() => setOwnPanelOpen(false)} />}

          <div className="tf-section">
            <label className="tf-label" htmlFor="tf-amount">
              보낼 금액
            </label>
            <div className={`tf-amount ${overBalance ? 'over' : ''}`}>
              <input
                id="tf-amount"
                inputMode="numeric"
                autoComplete="off"
                placeholder="0"
                value={amount ? Number(amount).toLocaleString('ko-KR') : ''}
                onChange={(e) => setAmount(e.target.value.replace(/\D/g, '').slice(0, 12))}
              />
              <span className="tf-amount-unit">원</span>
            </div>
            <p className={`tf-amount-hint ${overBalance ? 'error' : 'muted'}`}>
              {overBalance ? '출금 가능 금액보다 많아요' : amountValue > 0 ? koreanWon(amountValue) : ' '}
            </p>
            <span className="quick-amounts">
              {QUICK_AMOUNTS.map((q) => (
                <button key={q} type="button" className="chip" onClick={() => setAmount(String(amountValue + q))}>
                  +{q / 10_000}만
                </button>
              ))}
              <button type="button" className="chip" onClick={() => setAmount(String(source.balance))}>
                전액
              </button>
              {amount && (
                <button type="button" className="chip ghost" onClick={() => setAmount('')}>
                  지우기
                </button>
              )}
            </span>
          </div>

          {step.kind === 'form' && step.error && <ErrorState message={step.error}>{null}</ErrorState>}
          <button className="button primary tf-submit" disabled={!canCheck || overBalance}>
            {step.kind === 'checking' ? '받는 분 확인 중…' : '다음'}
          </button>
        </form>
      )}

      {source && 'holder' in step && (
        <div className={`receipt status-${step.kind}`}>
          {step.kind === 'done' ? (
            <div className="receipt-head">
              {step.result.status === 'PENDING' ? (
                <span className="receipt-icon pending" aria-hidden="true">
                  <Clock size={36} />
                </span>
              ) : (
                <span className="receipt-icon success" aria-hidden="true">
                  <svg viewBox="0 0 52 52" width="56" height="56">
                    <circle className="check-circle" cx="26" cy="26" r="24" fill="none" />
                    <path className="check-mark" fill="none" d="M15 27 l7 7 l15 -15" />
                  </svg>
                </span>
              )}
              <p className="receipt-title">
                <strong>{step.holder.holder_name}</strong>님에게
                <br />
                {won(amountValue)}을 {step.result.status === 'PENDING' ? '보내는 중이에요' : '보냈어요'}
              </p>
            </div>
          ) : step.kind === 'blocked' || step.kind === 'refunded' || step.kind === 'failed' ? (
            <div className="receipt-head">
              <span className="receipt-icon danger" aria-hidden="true">
                <CircleX size={36} />
              </span>
              <p className="receipt-title">
                {step.kind === 'blocked' ? '이체를 막았어요' : step.kind === 'refunded' ? '돈을 돌려받았어요' : '이체하지 못했어요'}
              </p>
            </div>
          ) : (
            <div className="receipt-head">
              <span className="receipt-avatar" aria-hidden="true">
                {step.holder.holder_name.slice(0, 1)}
              </span>
              <p className="receipt-title">
                <strong>{step.holder.holder_name}</strong>님에게
                <br />
                <span className="receipt-amount">{won(amountValue)}</span>
                <br />
                보낼까요?
              </p>
            </div>
          )}

          <dl className="receipt-rows">
            <dt>받는 분</dt>
            <dd>{step.holder.holder_name}</dd>
            <dt>받는 계좌</dt>
            <dd>
              {step.holder.bank_name}
              <br />
              <span className="nowrap">{step.holder.to_account_num}</span>
            </dd>
            <dt>출금 계좌</dt>
            <dd>
              {source.nickname ?? '입출금'} ({source.account_num.slice(-4)})
            </dd>
            <dt>{step.kind === 'done' ? '보낸 금액' : '보낼 금액'}</dt>
            <dd className="strong">{won(amountValue)}</dd>
            {step.kind === 'done' && (
              <>
                <dt>남은 잔액</dt>
                <dd>{won(step.result.balance_after)}</dd>
              </>
            )}
            {step.kind === 'refunded' && step.balanceAfter != null && (
              <>
                <dt>남은 잔액</dt>
                <dd>{won(step.balanceAfter)}</dd>
              </>
            )}
            {sentAt && (
              <>
                <dt>보낸 시각</dt>
                <dd>{dateTime(sentAt)}</dd>
              </>
            )}
          </dl>

          {(step.kind === 'confirm' || step.kind === 'sending') && (
            <>
              <p className="receipt-warning">
                <ShieldAlert size={18} aria-hidden="true" />
                받는 분 이름이 맞는지 꼭 확인하세요. 모르는 사람이 시켜서 보내는 돈이라면 보내지 마세요.
              </p>
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
                  <PinPad value={pin} onChange={setPin} autoFocus />
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
              돈은 출금됐고, {step.holder.bank_name}에서 받았는지 확인하고 있어요. 확인되면 아래 "다른 은행 이체"에
              완료로 바뀌어요. 받는 은행이 거절하면 돈을 돌려드려요.
            </p>
          )}
          {step.kind === 'refunded' && <p className="error">{step.message}</p>}
          {step.kind === 'failed' && <p className="error">{step.message}</p>}

          {['done', 'blocked', 'refunded', 'failed'].includes(step.kind) && (
            <div className="button-row">
              <Link className="button" to={`/accounts/checking/${source.account_id}`}>
                거래내역 보기
              </Link>
              <button className="button primary" onClick={reset}>
                {step.kind === 'done' ? '확인' : '다시 보내기'}
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
              <RefreshCw size={16} aria-hidden="true" /> 새로고침
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
