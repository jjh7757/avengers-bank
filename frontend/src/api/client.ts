/**
 * fetch 래퍼: JWT 첨부, { data } 풀기, 오류는 ApiError로.
 *
 * access 토큰은 메모리에만 둔다(localStorage에 두면 XSS로 훔칠 수 있다). 로그인 유지는 서버가 준
 * httpOnly refresh 쿠키가 맡는다: 새로고침하거나 access 토큰이 만료(401)되면 /users/refresh로 새로 받는다.
 * refresh도 실패하면 로그아웃 이벤트를 보낸다.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'
const LEGACY_TOKEN_KEY = 'avengers.access_token' // 예전 버전이 localStorage에 남긴 토큰

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

let accessToken: string | null = null

try {
  localStorage.removeItem(LEGACY_TOKEN_KEY)
} catch {
  /* 저장소를 못 쓰는 환경 */
}

export const tokenStore = {
  get: (): string | null => accessToken,
  set: (token: string) => {
    accessToken = token
  },
  clear: () => {
    accessToken = null
  },
}

/** AuthProvider가 듣고 로그아웃 처리한다 */
export const UNAUTHORIZED_EVENT = 'avengers:unauthorized'

let refreshing: Promise<boolean> | null = null

/** refresh 쿠키로 새 access 토큰을 받는다. 동시에 여러 요청이 401을 받아도 갱신은 한 번만 한다. */
export function refreshAccessToken(): Promise<boolean> {
  refreshing ??= fetch(`${BASE_URL}/users/refresh`, { method: 'POST', credentials: 'same-origin' })
    .then(async (response) => {
      if (!response.ok) return false
      const body = await response.json().catch(() => null)
      const token = body?.data?.access_token
      if (typeof token !== 'string') return false
      accessToken = token
      return true
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

interface Options {
  method?: string
  body?: unknown
  headers?: Record<string, string>
}

async function send(path: string, options: Options): Promise<Response> {
  const headers: Record<string, string> = { ...options.headers }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  const isForm = options.body instanceof FormData // 파일 업로드: 브라우저가 multipart 경계를 붙이게 둔다
  if (options.body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  try {
    return await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      credentials: 'same-origin',
      body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', '서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.')
  }
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const hadToken = accessToken !== null
  let response = await send(path, options)

  // access 토큰 만료: 한 번만 갱신하고 같은 요청을 다시 보낸다
  if (response.status === 401 && hadToken) {
    if (await refreshAccessToken()) {
      response = await send(path, options)
    } else {
      accessToken = null
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
  }

  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const error = body?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'HTTP_ERROR',
      error?.message ?? '요청을 처리할 수 없어요.',
      error?.extra ?? null,
    )
  }
  return body.data as T
}

/** 이체 한 건마다 새로 만든다. 같은 이체를 다시 보낼 때(PIN 입력 후, 네트워크 재시도)는 같은 키를 쓴다 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}
