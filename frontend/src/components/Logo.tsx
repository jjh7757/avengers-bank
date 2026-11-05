/** AvengersBank 로고: 둥근 사각형 안에 A 모양 심볼 + 글자 */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="ab-logo-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3b7bf0" />
          <stop offset="1" stopColor="#1a4fb8" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#ab-logo-bg)" />
      <path d="M9 23 L16 8.5 L23 23" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="19" r="2.4" fill="#ffd25e" />
    </svg>
  )
}

export default function Logo({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <span className={`logo ${className}`}>
      <LogoMark size={size} />
      <span className="logo-text">
        Avengers<b>Bank</b>
      </span>
    </span>
  )
}
