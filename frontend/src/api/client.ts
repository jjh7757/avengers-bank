/** fetch 래퍼: JWT 첨부, { data } 풀기, 오류는 ApiError로. 401이면 로그인 화면으로 보낸다. */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'
const TOKEN_KEY = 'avengers.access_token'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly extra: Record<string, unknown> | null

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.extra = extra
  }
}

export const tokenStore = {
  get: (): string | null => {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set: (token: string) => {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      /* 저장소를 못 쓰는 환경: 이번 탭에서만 유지 */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* 무시 */
    }
  },
}

/** AuthProvider가 듣고 로그아웃 처리한다 */
export const UNAUTHORIZED_EVENT = 'avengers:unauthorized'

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.')
  }

  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const error = body?.error
    if (response.status === 401 && token) {
      tokenStore.clear()
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    throw new ApiError(
      response.status,
      error?.code ?? 'HTTP_ERROR',
      error?.message ?? '요청을 처리할 수 없어요.',
      error?.extra ?? null,
    )
  }
  return body.data as T
}
