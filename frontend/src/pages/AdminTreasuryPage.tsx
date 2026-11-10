import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { adminApi } from '../api/endpoints'
import type { AdminAuditLog, ReserveRequest, Treasury } from '../api/types'
import { useAuth } from '../auth/useAuth'
import ReserveRequestForm from '../components/ReserveRequestForm'
import { ErrorState, SkeletonList } from '../components/ui'
import { kstDateTime, won } from '../lib/format'
import {
  adminErrorMessage,
  AUDIT_ACTION_LABEL,
  auditSummary,
  HUB_RESERVE_ERROR_LABEL,
  isAdminRevoked,
  isOpenStatus,
  RESERVE_KIND_LABEL,
  RESERVE_STATUS_LABEL,
} from '../lib/treasury'

interface Loaded {
  treasury: Treasury
  requests: ReserveRequest[]
  logs: AdminAuditLog[]
}

type Notice = { tone: 'success' | 'caution' | 'error'; text: string }

async function fetchAll(): Promise<Loaded> {
  const [treasury, requests, logs] = await Promise.all([
    adminApi.treasury(),
    adminApi.reserveRequests(),
    adminApi.auditLogs(50),
  ])
  return { treasury, requests, logs }
}

/**
 * 관리자 자금 관리: 은행 자산(금고 현금 ↔ 허브 예치금)만 다룬다. 고객 잔액은 건드리지 않는다.
 * 예치금 신청은 허브(ClearingHub) 관리자가 승인해야 반영되고, "허브와 동기화"로 결정을 가져온다.
 */
export default function AdminTreasuryPage() {
  const { refresh } = useAuth()
  const [data, setData] = useState<Loaded | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloading, setReloading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [cancelId, setCancelId] = useState<number | null>(null)

  // 403 ADMIN_REQUIRED: 내 정보를 다시 읽으면 역할이 CUSTOMER가 되고, 라우트(RequireAdmin)가 "관리자만" 안내 + 홈으로를 보여 준다
  const onRevoked = useCallback(() => {
    refresh().catch(() => {})
  }, [refresh])

  // 성공하면 데이터를 바꾸고, 실패하면 이전 데이터는 그대로 두고 오류만 보여 준다 (신청·동기화 뒤 다시 읽을 때도 같음)
  const load = useCallback(
    () =>
      fetchAll().then(
        (loaded) => {
          setData(loaded)
          setLoadError(null)
        },
        (e) => {
          if (isAdminRevoked(e)) return onRevoked()
          setLoadError(adminErrorMessage(e, '불러오지 못했어요.'))
        },
      ),
    [onRevoked],
  )

  useEffect(() => {
    void load()
  }, [load])

  async function reload() {
    setReloading(true)
    await load()
    setReloading(false)
  }

  async function act(run: () => Promise<Notice>) {
    setBusy(true)
    setNotice(null)
    try {
      setNotice(await run())
    } catch (e) {
      if (isAdminRevoked(e)) return onRevoked()
      setNotice({ tone: 'error', text: adminErrorMessage(e, '처리하지 못했어요.') })
    } finally {
      setBusy(false)
      setCancelId(null)
      await load() // 성공·실패 모두 현황·내역·감사 로그가 바뀔 수 있다
    }
  }

  const sync = () =>
    act(async () => {
      const changed = await adminApi.syncReserveRequests()
      if (changed.length === 0) return { tone: 'success', text: '허브와 맞췄어요. 바뀐 신청은 없어요.' }
      const list = changed.map((r) => `#${r.request_id} ${RESERVE_STATUS_LABEL[r.status] ?? r.status}`).join(', ')
      return { tone: 'success', text: `허브와 맞췄어요. 바뀐 신청 ${changed.length}건: ${list}` }
    })

  const cancel = (id: number) =>
    act(async () => {
      const result = await adminApi.cancelReserveRequest(id)
      if (result.status === 'CANCELLED') return { tone: 'success', text: `신청 #${id}을 취소했어요.` }
      return {
        tone: 'caution',
        text: `신청 #${id}은 그사이 허브가 결정해서 ‘${RESERVE_STATUS_LABEL[result.status] ?? result.status}’ 상태로 맞췄어요.`,
      }
    })

  return (
    <section className="page treasury-page">
      <div className="treasury-head">
        <h1>자금 관리</h1>
        <button className="button small" onClick={() => void reload()} disabled={reloading || busy}>
          <RefreshCw size={16} aria-hidden="true" /> {reloading ? '불러오는 중…' : '새로 고침'}
        </button>
      </div>
      <p className="muted small treasury-intro">
        은행 자산(금고 현금 ↔ 허브 예치금)만 다뤄요. 고객 계좌 잔액은 바뀌지 않아요.
      </p>

      {!data && !loadError && <SkeletonList rows={4} height={88} />}
      {loadError && !data && <ErrorState message={loadError} />}
      {loadError && data && (
        <p className="error small" role="alert">
          {loadError}
        </p>
      )}

      {data && (
        <>
          <TreasuryStatus treasury={data.treasury} />

          <h2>예치금 신청</h2>
          <ReserveRequestForm treasury={data.treasury} onDone={() => void load()} onRevoked={onRevoked} />

          <div className="treasury-section-head">
            <h2>신청 내역</h2>
            <button
              className="button small primary"
              onClick={() => void sync()}
              disabled={busy || !data.treasury.interbank_enabled}
            >
              <RefreshCw size={16} aria-hidden="true" /> {busy ? '처리 중…' : '허브와 동기화'}
            </button>
          </div>
          {notice && (
            <p className={`reserve-result ${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>
              {notice.text}
            </p>
          )}
          {data.requests.length === 0 ? (
            <p className="muted">아직 신청이 없어요.</p>
          ) : (
            <div className="table-wrap">
              <table className="table" aria-label="예치금 신청 내역">
                <thead>
                  <tr>
                    <th>번호</th>
                    <th>종류</th>
                    <th>금액</th>
                    <th>상태</th>
                    <th>거절 사유</th>
                    <th>메모</th>
                    <th>신청 시각</th>
                    <th>결정 시각</th>
                    <th>반영 뒤 허브 잔액</th>
                    <th>
                      <span className="sr-only">취소</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.requests.map((r) => (
                    <tr key={r.request_id}>
                      <td className="num">#{r.request_id}</td>
                      <td>{RESERVE_KIND_LABEL[r.kind] ?? r.kind}</td>
                      <td className="num">{won(r.amount)}</td>
                      <td>
                        <span className={`status-badge status-${r.status.toLowerCase()}`}>
                          {RESERVE_STATUS_LABEL[r.status] ?? r.status}
                        </span>
                      </td>
                      <td className="wrap">{r.reject_reason ?? '-'}</td>
                      <td className="wrap">{r.memo || '-'}</td>
                      <td>{kstDateTime(r.created_at)}</td>
                      <td>{r.decided_at ? kstDateTime(r.decided_at) : '-'}</td>
                      <td className="num">{r.hub_balance_after != null ? won(r.hub_balance_after) : '-'}</td>
                      <td>
                        {isOpenStatus(r.status) &&
                          (cancelId === r.request_id ? (
                            <span className="inline-confirm">
                              <button className="button small danger" onClick={() => void cancel(r.request_id)} disabled={busy}>
                                취소 확정
                              </button>
                              <button className="button small" onClick={() => setCancelId(null)} disabled={busy}>
                                아니요
                              </button>
                            </span>
                          ) : (
                            <button
                              className="button small"
                              onClick={() => setCancelId(r.request_id)}
                              disabled={busy}
                              aria-label={`신청 #${r.request_id} 취소`}
                            >
                              취소
                            </button>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2>감사 로그</h2>
          <p className="muted small">관리자가 한 신청·취소·동기화 (실패한 시도 포함). 최근 50건.</p>
          {data.logs.length === 0 ? (
            <p className="muted">아직 기록이 없어요.</p>
          ) : (
            <div className="table-wrap">
              <table className="table" aria-label="감사 로그">
                <thead>
                  <tr>
                    <th>시각</th>
                    <th>관리자</th>
                    <th>행동</th>
                    <th>대상</th>
                    <th>결과</th>
                    <th>내용</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {data.logs.map((log) => (
                    <tr key={log.log_id}>
                      <td>{kstDateTime(log.created_at)}</td>
                      <td>{log.admin_login_id}</td>
                      <td>{AUDIT_ACTION_LABEL[log.action] ?? log.action}</td>
                      <td>{log.target ? `신청 #${log.target}` : '-'}</td>
                      <td>
                        {log.result === 'OK' ? (
                          <span className="status-badge status-approved">OK</span>
                        ) : (
                          <span className="status-badge status-failed">FAILED{log.error_code ? ` · ${log.error_code}` : ''}</span>
                        )}
                      </td>
                      <td className="wrap">{auditSummary(log)}</td>
                      <td>{log.client_ip ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="muted small treasury-footnote">
            실제 은행은 신청자와 승인자를 나누는 내부 결재가 한 단계 더 있어요. 여기서는 은행 신청 → 허브(중앙은행 역할) 관리자
            승인 두 단계로 갈음해요.
          </p>
        </>
      )}
    </section>
  )
}

/** 현황 카드: 금고 현금, 예치금(우리 장부 vs 허브), 보낼 수 있는 금액, 결정 대기, 중간 계정, 대사 결과 */
function TreasuryStatus({ treasury: t }: { treasury: Treasury }) {
  const hub = t.hub_reserve
  const hubBalance = hub?.balance ?? null
  const mismatch = hubBalance != null && hubBalance !== t.ledger_hub_reserve
  const hubError = t.hub_reserve_error
    ? (HUB_RESERVE_ERROR_LABEL[t.hub_reserve_error] ?? `허브 오류 (${t.hub_reserve_error})`)
    : null

  return (
    <>
      <div className="treasury-grid">
        <div className="stat-card">
          <span className="stat-label">금고 현금</span>
          <strong className="stat-value">{won(t.vault_cash)}</strong>
          <span className="muted small">입금 신청 가능 {won(t.deposit_available)}</span>
        </div>

        <div className={`stat-card stat-wide ${mismatch ? 'stat-warn' : ''}`}>
          <span className="stat-label">허브 예치금</span>
          <div className="stat-pair">
            <span>
              <span className="muted small">우리 장부</span>
              <strong className="stat-value">{won(t.ledger_hub_reserve)}</strong>
            </span>
            <span>
              <span className="muted small">허브 값</span>
              <strong className="stat-value">{hubBalance != null ? won(hubBalance) : '허브 값 없음'}</strong>
            </span>
          </div>
          {mismatch && (
            <p className="stat-note" role="status">
              <AlertTriangle size={16} aria-hidden="true" /> 두 값이 {won(Math.abs(hubBalance - t.ledger_hub_reserve))}{' '}
              달라요. 허브 승인 뒤 아직 동기화 전이거나 정산 반영 전일 수 있어요. ‘허브와 동기화’를 눌러 보세요.
            </p>
          )}
          {!hub && hubError && <p className="stat-note">{hubError}</p>}
        </div>

        <div className="stat-card">
          <span className="stat-label">보낼 수 있는 금액</span>
          <strong className="stat-value">{hub?.available != null ? won(hub.available) : '-'}</strong>
          <span className="muted small">
            순채무한도 {hub?.net_debit_cap != null ? won(hub.net_debit_cap) : '-'}
            {hub?.exposure ? ` · 미정산 ${won(hub.exposure)}` : ''}
          </span>
        </div>

        <div className="stat-card">
          <span className="stat-label">결정 대기 신청</span>
          <strong className="stat-value">{t.open_request_count}건</strong>
          <span className="muted small">
            입금 {t.open_deposit_count}건({won(t.open_deposit_amount)}) · 인출 {t.open_withdraw_count}건
          </span>
        </div>

        <div className="stat-card">
          <span className="stat-label">중간 계정</span>
          <strong className="stat-value">{won(t.suspense_balance)}</strong>
          <span className="muted small">고객 계좌에서 빠졌지만 아직 확정 안 된 타행 송금</span>
        </div>
      </div>

      {t.reconcile_problems.length === 0 ? (
        <p className="reconcile ok">
          <CheckCircle2 size={18} aria-hidden="true" /> 장부 일치 (대사 문제 없음)
        </p>
      ) : (
        <div className="reconcile warn" role="alert">
          <p>
            <AlertTriangle size={18} aria-hidden="true" /> 장부 대사 불일치 {t.reconcile_problems.length}건
          </p>
          <ul>
            {t.reconcile_problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted small">확인 시각 {kstDateTime(t.checked_at)} (한국 시간)</p>
    </>
  )
}
