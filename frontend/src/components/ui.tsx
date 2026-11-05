import { Landmark, PiggyBank, Wallet, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { AccountType, CardType } from '../api/types'
import { CARD_TYPE_LABEL } from '../lib/format'
import { LogoMark } from './Logo'

const ACCOUNT_ICON: Record<AccountType, LucideIcon> = { checking: Wallet, deposit: Landmark, savings: PiggyBank }

/** 계좌 종류별 동그란 아이콘 */
export function AccountIcon({ type }: { type: AccountType }) {
  const Icon = ACCOUNT_ICON[type]
  return (
    <span className={`account-icon account-icon-${type}`} aria-hidden="true">
      <Icon size={22} strokeWidth={2.2} />
    </span>
  )
}

/** 실물 카드 모양. 번호는 뒤 4자리만 보여 준다 */
export function CardVisual({ type, cardNum, compact = false }: { type: CardType; cardNum: string; compact?: boolean }) {
  return (
    <div className={`card-visual card-visual-${type} ${compact ? 'compact' : ''}`} aria-label={`${CARD_TYPE_LABEL[type]} 끝자리 ${cardNum.slice(-4)}`}>
      <div className="card-visual-top">
        <span className="card-visual-brand">
          <LogoMark size={22} /> AvengersBank
        </span>
        <span className="card-visual-type">{CARD_TYPE_LABEL[type]}</span>
      </div>
      <span className="card-visual-chip" aria-hidden="true" />
      <span className="card-visual-num" aria-hidden="true">
        ••••&nbsp;&nbsp;••••&nbsp;&nbsp;••••&nbsp;&nbsp;{cardNum.slice(-4)}
      </span>
    </div>
  )
}

/** 불러오는 동안 보여 줄 회색 자리 */
export function SkeletonList({ rows = 3, height = 72 }: { rows?: number; height?: number }) {
  return (
    <ul className="list" aria-busy="true" aria-label="불러오는 중">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="skeleton" style={{ height }} />
      ))}
    </ul>
  )
}

export function Skeleton({ width = '100%', height = 20 }: { width?: number | string; height?: number }) {
  return <span className="skeleton skeleton-inline" style={{ width, height }} aria-hidden="true" />
}

/** 목록이 비었을 때: 아이콘 + 설명 + 다음 행동 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description?: string
  action?: { to: string; label: string }
}) {
  return (
    <div className="empty-state">
      <span className="empty-state-icon" aria-hidden="true">
        <Icon size={32} />
      </span>
      <p className="empty-state-title">{title}</p>
      {description && <p className="muted small">{description}</p>}
      {action && (
        <Link className="button primary small" to={action.to}>
          {action.label}
        </Link>
      )}
    </div>
  )
}

export function ErrorState({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div className="error-state" role="alert">
      <p>{message}</p>
      {children ?? (
        <button className="button small" onClick={() => window.location.reload()}>
          다시 시도
        </button>
      )}
    </div>
  )
}
