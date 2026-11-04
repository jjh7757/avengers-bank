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
  tts_text: string
}

export interface AccountSummaryCard {
  type: 'account_summary'
  accounts: { account_type: AccountType; account_id: number; balance: number; nickname: string | null; account_num: string }[]
}

export type ChatCard = TransferConfirmationCard | AccountSummaryCard

export interface ChatMessage {
  msg_id: number
  role: 'user' | 'assistant'
  content: string
  intent: string | null
  input_mode: 'text' | 'voice'
  card: ChatCard | null
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
}

export interface RuleHit {
  code: string
  name: string
  level: string
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

export interface FdsLog {
  fds_log_id: number
  session_id: string | null
  from_account: string
  to_account: string
  amount: number
  rule_hits: { code: string; name: string; level: string }[]
  ml_score: number | null
  top_factors: Factor[]
  risk_level: string
  decision: string
  input_mode: string
  created_at: string
}
