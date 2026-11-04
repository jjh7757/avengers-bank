export const won = (amount: number) => `${amount.toLocaleString('ko-KR')}원`

export const signedWon = (amount: number) => `${amount > 0 ? '+' : ''}${won(amount)}`

export const dateTime = (iso: string) =>
  new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`).toLocaleString('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

/** 화면에도 뒤 4자리만 크게: 110-123-456789 → 110-***-**6789 */
export const maskAccount = (num: string) => num.replace(/^(\d+)-(\d+)-(\d+)$/, (_, a, b: string, c: string) => `${a}-${'*'.repeat(b.length)}-${'*'.repeat(c.length - 4)}${c.slice(-4)}`)

export const ACCOUNT_TYPE_LABEL: Record<string, string> = { checking: '입출금', deposit: '예금', savings: '적금' }
export const CARD_TYPE_LABEL: Record<string, string> = { credit: '신용카드', debit: '체크카드' }
export const HISTORY_TYPE_LABEL: Record<string, string> = {
  DEPOSIT: '입금',
  WITHDRAW: '출금',
  TRANSFER_IN: '이체 받음',
  TRANSFER_OUT: '이체 보냄',
  CARD_PAYMENT: '카드 결제',
  SAVINGS_PAYMENT: '적금 납입',
  DEPOSIT_PAYMENT: '예금 입금',
  INTEREST: '이자',
}
