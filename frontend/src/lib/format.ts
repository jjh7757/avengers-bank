export const won = (amount: number) => `${amount.toLocaleString('ko-KR')}원`

/** 억·만 단위로 읽기 쉬운 금액: 1,250,000 → "125만원", 105,003,000 → "1억 500만 3,000원" */
export const koreanWon = (amount: number) => {
  if (amount <= 0) return ''
  const eok = Math.floor(amount / 100_000_000)
  const man = Math.floor((amount % 100_000_000) / 10_000)
  const rest = amount % 10_000
  const parts = [eok && `${eok.toLocaleString('ko-KR')}억`, man && `${man.toLocaleString('ko-KR')}만`, rest && rest.toLocaleString('ko-KR')]
  return `${parts.filter(Boolean).join(' ')}원`
}

export const signedWon =(amount: number) => `${amount > 0 ? '+' : ''}${won(amount)}`

export const dateTime = (iso: string) =>
  new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).toLocaleString('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

/** 연도까지 한국 시간으로: "2026. 11. 10. 14:05" (관리자 화면: 기기 시간대와 상관없이 KST) */
export const kstDateTime = (iso: string) =>
  new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

/** 화면에도 뒤 4자리만 크게: 110-123-456789 → 110-***-**6789 */
export const maskAccount = (num: string) => num.replace(/^(\d+)-(\d+)-(\d+)$/, (_, a, b: string, c: string) => `${a}-${'*'.repeat(b.length)}-${'*'.repeat(c.length - 4)}${c.slice(-4)}`)

export const ACCOUNT_TYPE_LABEL: Record<string, string> = { checking: '입출금', deposit: '예금', savings: '적금' }
export const CARD_TYPE_LABEL: Record<string, string> = { credit: '신용카드', debit: '체크카드' }
export const FDS_DECISION_LABEL: Record<string, string> = {
  PASS: '통과',
  PASS_WITH_AUTH: 'PIN 확인 후 통과',
  AUTH_REQUIRED: 'PIN 요청',
  AUTH_FAILED: 'PIN 틀림',
  BLOCKED: '차단',
}
export const HISTORY_TYPE_LABEL: Record<string, string> = {
  DEPOSIT: '입금',
  WITHDRAW: '출금',
  TRANSFER_IN: '이체 받음',
  TRANSFER_OUT: '이체 보냄',
  TRANSFER_REFUND: '이체 반환',
  CARD_PAYMENT: '카드 결제',
  SAVINGS_PAYMENT: '적금 납입',
  DEPOSIT_PAYMENT: '예금 입금',
  INTEREST: '이자',
  CASH_DEPOSIT: '입금(시연)',
}
