/** 관리자 자금 관리 화면의 라벨과 오류 문장 */
import { ApiError } from '../api/client'
import type { AdminAuditLog, ReserveKind, ReserveStatus } from '../api/types'
import { won } from './format'

export const RESERVE_KIND_LABEL: Record<ReserveKind, string> = { DEPOSIT: '입금', WITHDRAW: '인출' }

export const RESERVE_STATUS_LABEL: Record<ReserveStatus, string> = {
  SENDING: '보내는 중',
  PENDING: '승인 대기',
  APPROVED: '승인',
  REJECTED: '거절',
  CANCELLED: '취소',
  FAILED: '실패',
}

/** 아직 허브 관리자의 결정 전: 취소할 수 있다 */
export const isOpenStatus = (status: string) => status === 'SENDING' || status === 'PENDING'

export const AUDIT_ACTION_LABEL: Record<string, string> = {
  RESERVE_REQUEST_CREATE: '예치금 신청',
  RESERVE_REQUEST_CANCEL: '신청 취소',
  RESERVE_SYNC: '허브 동기화',
}

/** hub_reserve가 null인 이유 */
export const HUB_RESERVE_ERROR_LABEL: Record<string, string> = {
  INTERBANK_DISABLED: '허브 연결 설정이 없어요 (HUB_URL 등)',
  HUB_TIMEOUT: '허브가 응답하지 않아요',
  HUB_ERROR: '허브에서 오류가 났어요',
}

const ERROR_MESSAGE: Record<string, string> = {
  INSUFFICIENT_VAULT_CASH: '금고 현금이 모자라요. 결정을 기다리는 입금 신청 금액을 뺀 "입금 신청 가능 금액" 안에서 신청해 주세요.',
  INTERBANK_DISABLED: '허브 연결 설정이 없어 신청·취소·동기화를 할 수 없어요. 서버의 허브 설정(HUB_URL 등)을 확인해 주세요.',
  HUB_UNAVAILABLE: '허브에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
  RESERVE_REQUEST_NOT_PENDING: '이미 허브 관리자가 결정한 신청이라 취소할 수 없어요. 내역을 새로 불러왔어요.',
  RESERVE_REQUEST_NOT_FOUND: '없는 신청이에요. 내역을 새로 불러왔어요.',
  ADMIN_REQUIRED: '관리자 권한이 없어요.',
  VALIDATION_ERROR: '입력값을 확인해 주세요. 금액은 1원 이상, 메모는 200자까지예요.',
}

export function adminErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback
  return ERROR_MESSAGE[error.code] ?? error.message
}

/** 쓰는 도중 관리자에서 강등됨 (역할은 매 요청 DB에서 읽으므로 같은 토큰도 바로 403) */
export const isAdminRevoked = (error: unknown) => error instanceof ApiError && error.code === 'ADMIN_REQUIRED'

/** 감사 로그 detail 한 줄 요약: "입금 600,000원 “11월 예치” → 승인 대기" / "바뀐 신청 2건" */
export function auditSummary(log: AdminAuditLog): string {
  const d = log.detail
  const parts: string[] = []
  if (typeof d.kind === 'string') parts.push(RESERVE_KIND_LABEL[d.kind as ReserveKind] ?? d.kind)
  if (typeof d.amount === 'number') parts.push(won(d.amount))
  if (typeof d.memo === 'string' && d.memo) parts.push(`“${d.memo}”`)
  if (typeof d.status === 'string') parts.push(`→ ${RESERVE_STATUS_LABEL[d.status as ReserveStatus] ?? d.status}`)
  if (Array.isArray(d.changed)) parts.push(`바뀐 신청 ${d.changed.length}건`)
  return parts.join(' ') || '-'
}
