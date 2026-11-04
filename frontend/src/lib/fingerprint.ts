/**
 * FDS "새 기기" 판정용 기기 식별값: 브라우저 정보의 SHA-256 해시 앞 32자.
 * 보안 수단이 아니라 같은 브라우저인지 대략 구분하는 용도다 (PROJECT_PLAN.md 4-2).
 */
let cached: Promise<string> | null = null

export function deviceFingerprint(): Promise<string> {
  cached ??= (async () => {
    const parts = [
      navigator.userAgent,
      navigator.language,
      navigator.hardwareConcurrency,
      `${screen.width}x${screen.height}x${screen.colorDepth}`,
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    ].join('|')
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(parts))
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32)
  })()
  return cached
}
