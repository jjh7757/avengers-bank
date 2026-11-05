import { api } from './client'
import type {
  AccountDetail,
  AccountHistory,
  AccountSummary,
  AccountType,
  CardDetail,
  CardHistory,
  CardSummary,
  CardType,
  ChatMessage,
  ProductKind,
  ProductTerms,
  FdsLog,
  Product,
  UiContext,
  TransferResult,
  User,
  VoiceProfile,
} from './types'

export const authApi = {
  signup: (body: { login_id: string; password: string; name: string; nick_name: string | null; phone: string }) =>
    api<User>('/users/signup', { method: 'POST', body }),
  login: (body: { login_id: string; password: string }) =>
    api<{ access_token: string }>('/users/login', { method: 'POST', body }),
  me: () => api<User>('/users/me'),
  setPin: (password: string, pin: string) => api<User>('/users/me/pin', { method: 'PUT', body: { password, pin } }),
}

export const accountApi = {
  list: () => api<AccountSummary[]>('/accounts'),
  get: (type: AccountType, id: number) => api<AccountDetail>(`/accounts/${type}/${id}`),
  /** 한도를 높일 때는 pin이 필요하다 (PIN_NOT_SET / PIN_REQUIRED / INVALID_PIN) */
  update: (
    type: AccountType,
    id: number,
    body: { nickname?: string; per_transfer_limit?: number; daily_transfer_limit?: number; pin?: string },
  ) => api<AccountDetail>(`/accounts/${type}/${id}`, { method: 'PATCH', body }),
  histories: (type: AccountType, id: number) => api<AccountHistory[]>(`/accounts/${type}/${id}/histories`),
  /** 계좌 개설. terms_version = 사용자가 동의한 이용약관 버전 (없거나 바뀌었으면 TERMS_NOT_AGREED) */
  open: (type: AccountType, body: Record<string, unknown> & { product_id: number; terms_version: string }) =>
    api<AccountDetail>(`/accounts/${type}`, { method: 'POST', body }),
}

export const cardApi = {
  list: () => api<CardSummary[]>('/cards'),
  get: (type: CardType, id: number) => api<CardDetail>(`/cards/${type}/${id}`),
  histories: (type: CardType, id: number) => api<CardHistory[]>(`/cards/${type}/${id}/histories`),
  /** 카드 발급. terms_version = 사용자가 동의한 이용약관 버전 */
  issue: (type: CardType, body: Record<string, unknown> & { product_id: number; terms_version: string }) =>
    api<CardDetail>(`/cards/${type}`, { method: 'POST', body }),
}

export const productApi = {
  accounts: () => api<Product[]>('/products/accounts'),
  cards: () => api<Product[]>('/products/cards'),
  get: (kind: ProductKind, id: number) => api<Product>(`/products/${kind}s/${id}`),
  terms: (kind: ProductKind, id: number) => api<ProductTerms>(`/products/${kind}s/${id}/terms`),
}

export const chatApi = {
  createSession: () => api<{ session_id: string; created_at: string }>('/chat/sessions', { method: 'POST' }),
  messages: (sessionId: string) => api<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`),
  send: (sessionId: string, text: string, inputMode: 'text' | 'voice', uiContext?: UiContext) =>
    api<{ user_message: ChatMessage; assistant_message: ChatMessage }>(`/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: { text, input_mode: inputMode, ui_context: uiContext },
    }),
}

export interface TransferRequest {
  from_checking_account_id: number
  to_account_num: string
  amount: number
  session_id?: string
  confirmation_token?: string
  pin?: string
  device_fingerprint?: string
  voice_approval_token?: string
  input_mode?: 'text' | 'voice'
}

export const transferApi = {
  transfer: (body: TransferRequest) => api<TransferResult>('/transfers', { method: 'POST', body }),
  /** 내 입출금 → 내 적금 (amount를 비우면 월 납입액) */
  paySavings: (body: { from_checking_account_id: number; savings_account_id: number; amount?: number }) =>
    api<TransferResult>('/transfers/savings', { method: 'POST', body }),
  /** 내 입출금 → 내 예금 */
  payDeposit: (body: { from_checking_account_id: number; deposit_account_id: number; amount: number }) =>
    api<TransferResult>('/transfers/deposit', { method: 'POST', body }),
}

export const voiceApi = {
  profile: () => api<VoiceProfile>('/voice/profile'),
  enroll: (password: string, recordings: Blob[]) => {
    const form = new FormData()
    form.append('password', password)
    form.append('consent', 'true')
    recordings.forEach((blob, i) => form.append('recordings', blob, `enroll-${i + 1}.wav`))
    return api<VoiceProfile>('/voice/profile', { method: 'POST', body: form })
  },
  remove: (password: string) => api<void>('/voice/profile', { method: 'DELETE', body: { password } }),
  approve: (sessionId: string, confirmationToken: string, recording: Blob) => {
    const form = new FormData()
    form.append('session_id', sessionId)
    form.append('confirmation_token', confirmationToken)
    form.append('recording', recording, 'approve.wav')
    return api<{ voice_approval_token: string }>('/voice/approvals', { method: 'POST', body: form })
  },
}

export const fdsApi = {
  logs: () => api<FdsLog[]>('/fds/logs?limit=100'),
}
