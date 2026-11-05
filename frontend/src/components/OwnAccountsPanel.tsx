import { useState } from 'react'

import { ApiError } from '../api/client'
import { authApi, transferApi } from '../api/endpoints'
import type { OwnAccount, OwnAccountsResult } from '../api/types'

const BIRTH_DATE = /^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$/
const RESULT_LABEL: Record<OwnAccountsResult['banks'][number]['result'], string> = {
  OK: '',
  UNSUPPORTED: '이 기능을 지원하지 않음',
  TIMEOUT: '응답 없음',
  ERROR: '불러오지 못함',
}

type Panel =
  | { kind: 'consent'; error?: string }
  | { kind: 'birth'; error?: string }
  | { kind: 'loading' }
  | { kind: 'list'; result: OwnAccountsResult }

/**
 * 다른 은행 내 계좌 불러오기 (ClearingHub SPEC 9절).
 * 동의 → (생년월일이 없으면 입력) → 허브가 같은 사람(가상 CI)의 계좌를 모아 준다 → 하나 고르면 이체 화면에 채운다.
 */
export default function OwnAccountsPanel({
  bankName,
  onPick,
  onClose,
}: {
  bankName: (code: string) => string
  onPick: (account: OwnAccount) => void
  onClose: () => void
}) {
  const [panel, setPanel] = useState<Panel>({ kind: 'consent' })
  const [agreed, setAgreed] = useState(false)
  const [birth, setBirth] = useState('')

  async function load() {
    setPanel({ kind: 'loading' })
    try {
      setPanel({ kind: 'list', result: await transferApi.ownAccounts() })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'BIRTH_DATE_REQUIRED') setPanel({ kind: 'birth' })
      else setPanel({ kind: 'consent', error: e instanceof ApiError ? e.message : '계좌를 불러오지 못했어요.' })
    }
  }

  async function saveBirthAndLoad() {
    try {
      await authApi.updateMe({ birth_date: birth })
    } catch (e) {
      setPanel({ kind: 'birth', error: e instanceof ApiError ? e.message : '생년월일을 저장하지 못했어요.' })
      return
    }
    await load()
  }

  return (
    <div className="chat-card own-accounts">
      <p className="chat-card-title">다른 은행 내 계좌</p>

      {panel.kind === 'consent' && (
        <>
          <label className="consent">
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
            <span>
              다른 은행에 내 이름으로 된 계좌가 있는지 확인하는 데 동의합니다.
              <span className="muted small"> 이름·생년월일·휴대폰번호로 만든 확인값만 보내고, 계좌번호는 가려서 보여 드려요.</span>
            </span>
          </label>
          {panel.error && <p className="error small">{panel.error}</p>}
          <div className="button-row">
            <button type="button" className="button" onClick={onClose}>
              닫기
            </button>
            <button type="button" className="button primary" disabled={!agreed} onClick={load}>
              불러오기
            </button>
          </div>
        </>
      )}

      {/* 이체 화면의 form 안에 그려지므로 form을 겹치지 않고 div + 버튼으로 처리한다 */}
      {panel.kind === 'birth' && (
        <div className="form">
          <label>
            생년월일 (8자리)
            <input
              inputMode="numeric"
              autoComplete="bday"
              placeholder="19900101"
              maxLength={8}
              value={birth}
              onChange={(e) => setBirth(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e) => {
                if (e.key !== 'Enter') return
                e.preventDefault() // 바깥 이체 form이 제출되지 않게
                if (BIRTH_DATE.test(birth)) saveBirthAndLoad()
              }}
              autoFocus
            />
            <span className="muted small">같은 사람인지 확인하는 데 필요해요. 한 번 등록하면 다음부터는 묻지 않아요.</span>
          </label>
          {panel.error && <p className="error small">{panel.error}</p>}
          <button type="button" className="button primary" disabled={!BIRTH_DATE.test(birth)} onClick={saveBirthAndLoad}>
            저장하고 불러오기
          </button>
        </div>
      )}

      {panel.kind === 'loading' && <p className="muted">다른 은행에 물어보는 중…</p>}

      {panel.kind === 'list' && (
        <>
          {panel.result.accounts.length === 0 ? (
            <p className="muted">다른 은행에서 내 명의 계좌를 찾지 못했어요.</p>
          ) : (
            <ul className="list">
              {panel.result.accounts.map((a) => (
                <li key={a.account_ref}>
                  <button type="button" className="list-item" onClick={() => onPick(a)}>
                    <span>
                      <strong>
                        {a.bank_name} {a.account_masked}
                      </strong>
                      <span className="muted small">{a.product_name || '입출금 계좌'}</span>
                    </span>
                    <span className="small">선택</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {panel.result.banks.some((b) => b.result !== 'OK') && (
            <p className="muted small">
              {panel.result.banks
                .filter((b) => b.result !== 'OK')
                .map((b) => `${bankName(b.bank_code)}: ${RESULT_LABEL[b.result]}`)
                .join(' · ')}
            </p>
          )}
          <button type="button" className="button link" onClick={onClose}>
            닫기
          </button>
        </>
      )}
    </div>
  )
}
