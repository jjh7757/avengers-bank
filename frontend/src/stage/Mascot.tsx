/** 도우미 캐릭터 "모아" (동전 저금통 모티프, 직접 그린 SVG). 표정·자세는 CSS(stage.css)가 mood 클래스로 바꾼다. */
export type Mood = 'idle' | 'listening' | 'thinking' | 'speaking' | 'bringing' | 'worried'

export default function Mascot({ mood }: { mood: Mood }) {
  return (
    <div className={`mascot mood-${mood}`} aria-hidden="true">
      <svg viewBox="0 0 140 150" className="mascot-svg">
        {/* 듣는 중: 귀 옆 소리 물결 */}
        <g className="m-waves">
          <path d="M14 70 q-8 10 0 20" />
          <path d="M6 64 q-12 16 0 32" />
        </g>
        {/* 생각 중: 머리 위 점 세 개 */}
        <g className="m-dots">
          <circle cx="52" cy="10" r="4" />
          <circle cx="66" cy="6" r="4" />
          <circle cx="80" cy="10" r="4" />
        </g>

        <g className="m-body-group">
          {/* 동전 투입구 */}
          <rect x="54" y="22" width="32" height="8" rx="4" className="m-slot" />
          {/* 몸통 */}
          <rect x="22" y="28" width="96" height="92" rx="40" className="m-body" />
          <ellipse cx="70" cy="104" rx="30" ry="10" className="m-belly" />
          {/* 볼 */}
          <ellipse cx="40" cy="84" rx="8" ry="5" className="m-cheek" />
          <ellipse cx="100" cy="84" rx="8" ry="5" className="m-cheek" />
          {/* 눈썹 (걱정할 때만 보임) */}
          <path d="M42 60 l14 -5" className="m-brow" />
          <path d="M98 60 l-14 -5" className="m-brow" />
          {/* 눈 */}
          <g className="m-eyes">
            <ellipse cx="52" cy="70" rx="6" ry="8" className="m-eye" />
            <ellipse cx="88" cy="70" rx="6" ry="8" className="m-eye" />
            <circle cx="54" cy="67" r="2" className="m-glint" />
            <circle cx="90" cy="67" r="2" className="m-glint" />
          </g>
          {/* 입: 기본 미소 / 말하는 입 / 걱정하는 입 */}
          <path d="M60 88 q10 9 20 0" className="m-mouth m-smile" />
          <ellipse cx="70" cy="91" rx="7" ry="5" className="m-mouth m-talk" />
          <path d="M60 93 q10 -6 20 0" className="m-mouth m-frown" />
          {/* 발 */}
          <rect x="40" y="114" width="18" height="12" rx="6" className="m-foot" />
          <rect x="82" y="114" width="18" height="12" rx="6" className="m-foot" />
        </g>

        {/* 팔: 화면을 가져올 때 오른팔을 뻗는다 */}
        <rect x="10" y="78" width="16" height="26" rx="8" className="m-arm m-arm-left" />
        <g className="m-arm-right">
          <rect x="114" y="78" width="16" height="26" rx="8" className="m-arm" />
        </g>
      </svg>
    </div>
  )
}
