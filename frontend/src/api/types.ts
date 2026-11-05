// 백엔드 응답 모양 (docs/API_ENDPOINTS.md)

export interface User {
  user_id: number
  login_id: string
  name: string
  nick_name: string | null
  phone: string
  has_pin: boolean
  created_at: string
}

export type AccountType = 'checking' | 'deposit' | 'savings'
export type CardType = 'credit' | 'debit'

export interface AccountSummary {
  account_type: AccountType
  account_id: number
  account_num: string
  balance: number
  nickname: string | null
  created_at: string
}

export interface AccountDetail extends AccountSummary {
  product_id: number
  per_transfer_limit: number | null
  daily_transfer_limit: number | null
  maturity_date: string | null
  monthly_payment: number | null
  monthly_deposit_date: number | null
}

export interface AccountHistory {
  history_id: number
  date: string
  amount: number
  type: string
  from_account: string | null
  sending_account: string | null
}

export interface CardSummary {
  card_type: CardType
  card_id: number
  card_num: string
  checking_account_id: number
  accumulated_amount: number
}

export interface CardDetail extends CardSummary {
  product_id: number
  payment_date: number | null
}

export interface Product {
  product_id: number
  type: 'CHECKING' | 'DEPOSIT' | 'SAVINGS' | 'CREDIT' | 'DEBIT'
  name: string
  description: string
  interest_rate?: string // 계좌 상품만 ("3.50")
}

export type ProductKind = 'account' | 'card'

/** 상품 이용약관 (GET /products/{accounts|cards}/{id}/terms). 동의하면 version을 개설·발급 요청에 넣는다 */
export interface ProductTerms {
  product_kind: ProductKind
  product_id: number
  product_type: Product['type']
  product_name: string
  title: string
  version: string
  sections: { title: string; text: string }[]
}

/** 가입 화면에 미리 채울 값 (모아가 대화에서 들은 조건) */
export interface SignupPrefill {
  term_months?: number
  monthly_payment?: number
  monthly_deposit_date?: number
  checking_account_id?: number
  payment_date?: number
}

export interface CardHistory {
  history_id: number
  place_of_use: string
  used_amount: number
  time: string
}

export interface TransferConfirmationCard {
  type: 'transfer_confirmation'
  from_checking_account_id: number
  from_account_num: string
  from_nickname: string | null
  from_balance: number
  to_account_num: string
  holder_name: string
  recipient_nickname: string | null
  amount: number
  amount_text: string
  insufficient_balance: boolean
  confirmation_token: string
  expires_at: string
  voice_enrolled: boolean // true면 버튼으로 승인할 때 PIN이 필요
  voice_challenge: string | null // 음성 승인 때 말할 숫자 "472" (서버가 음성 승인을 못 하면 null)
  voice_challenge_text: string | null // "사 칠 이"
  tts_text: string
  destination_type: 'checking' | 'savings' | 'deposit' // savings·deposit이면 승인 때 납입 API
  to_own: boolean // 내 다른 계좌로 옮기기
  to_account_id: number | null // to_own일 때 받는 내 계좌 id
  to_label: string | null // "내 월급 통장"
}

export interface AccountSummaryCard {
  type: 'account_summary'
  accounts: { account_type: AccountType; account_id: number; balance: number; nickname: string | null; account_num: string }[]
}

export type ChatCard = TransferConfirmationCard | AccountSummaryCard

/** 도우미 화면(/stage)에서 답변과 함께 가져올 화면. null이면 지금 화면 유지 */
export type Screen = 'home' | 'accounts' | 'account' | 'cards' | 'card' | 'products' | 'fds' | 'transfer' | 'signup'

/** 모아 화면에서 눌러 고른 항목 (백엔드 chat/schemas.UiSelected) */
export interface UiSelected {
  kind: 'account' | 'card' | 'product'
  label: string
  account_type?: AccountType
  account_id?: number
  card_type?: CardType
  card_id?: number
  product_kind?: 'account' | 'card'
  product_id?: number
}

/** 지금 사용자가 보고 있는 화면. 모아 화면이 메시지와 함께 보낸다 ("이거", "이 계좌"를 풀기 위해) */
export interface UiContext {
  screen: Screen | null
  screen_params: Record<string, unknown>
  selected: UiSelected | null
  visible: string[]
}

export interface ChatMessage {
  msg_id: number
  role: 'user' | 'assistant'
  content: string
  intent: string | null
  input_mode: 'text' | 'voice'
  card: ChatCard | null
  screen: Screen | null
  /** 화면의 대상·조건. account {account_type, account_id}, card {card_type, card_id}, products {kind, keyword, product_id} */
  screen_params: Record<string, unknown> | null
  created_at: string
}

export interface TransferResult {
  from_account_num: string
  to_account_num: string
  to_holder_name: string | null
  amount: number
  balance_after: number
  transferred_at: string
  risk_level: string | null
  /** 다른 은행 이체일 때 */
  to_bank?: string | null
  transfer_id?: string | null
  /** PENDING: 출금됐고 받는 은행이 확인 중 (다른 은행 이체만) */
  status?: 'COMPLETED' | 'PENDING'
}

export interface Bank {
  bank_code: string
  name: string
}

export interface HolderInquiryResult {
  to_bank: string
  bank_name: string
  to_account_num: string
  holder_name: string
}

export interface InterbankTransfer {
  transfer_id: string
  to_bank: string
  to_account: string
  to_holder_name: string | null
  amount: number
  status: 'PENDING' | 'COMPLETED' | 'FAILED'
  fail_code: string | null
  fail_message: string | null
  created_at: string
  finished_at: string | null
}

export interface RuleHit {
  code: string
  name: string
  level: string
  detail?: string // LLM 대화 판별 근거
}

export interface Factor {
  feature: string
  label: string
  contribution: number
}

/** FDS가 ADDITIONAL_AUTH_REQUIRED / FDS_BLOCKED / INVALID_PIN일 때 error.extra */
export interface FdsExtra {
  fds_log_id: number
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH'
  rule_hits: RuleHit[]
  ml_score: number | null
  top_factors: Factor[]
  warning?: string
  has_pin?: boolean
}

export interface VoiceProfile {
  enrolled: boolean
  available: boolean
  created_at: string | null
  updated_at: string | null
}

export interface FdsLog {
  fds_log_id: number
  session_id: string | null
  from_account: string
  to_account: string
  amount: number
  rule_hits: RuleHit[]
  ml_score: number | null
  top_factors: Factor[]
  risk_level: string
  decision: string
  input_mode: string
  created_at: string
}
