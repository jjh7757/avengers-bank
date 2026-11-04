import type { UiSelected } from '../api/types'

/** 모아 화면에서 목록 항목을 눌러 고르기 ("이거 가입해줘"의 "이거") */
export interface Pick {
  selectedKey: string | null
  onSelect: (selected: UiSelected) => void
}

export const selectionKey = (s: UiSelected) =>
  `${s.kind}:${s.account_type ?? s.card_type ?? s.product_kind}:${s.account_id ?? s.card_id ?? s.product_id}`
