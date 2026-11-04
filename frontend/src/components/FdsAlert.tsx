import type { FdsExtra } from '../api/types'

const AI_REASON_MIN_SCORE = 0.3 // 백엔드 MEDIUM 임계값 (fds_training/model/thresholds.json)

/** FDS 차단·추가 인증 사유. 규칙 이름과 모델이 꼽은 주요 요인을 보여 준다. */
export default function FdsAlert({ extra, blocked }: { extra: FdsExtra; blocked: boolean }) {
  return (
    <div className={`fds-alert ${blocked ? 'blocked' : 'caution'}`} role="alert">
      <p className="fds-title">{blocked ? '⛔ 이상거래가 의심되어 이체를 막았어요' : '⚠️ 평소와 다른 이체예요'}</p>
      {extra.warning && <p className="fds-warning">{extra.warning}</p>}
      {extra.rule_hits.length > 0 && (
        <>
          <p className="small muted">확인된 위험 신호</p>
          <ul className="fds-reasons">
            {extra.rule_hits.map((hit) => (
              <li key={hit.code}>{hit.name}</li>
            ))}
          </ul>
        </>
      )}
      {/* AI 점수가 낮으면 규칙이 잡은 것이므로 AI 근거는 보여 주지 않는다 */}
      {extra.ml_score != null && extra.ml_score >= AI_REASON_MIN_SCORE && extra.top_factors.length > 0 && (
        <p className="small muted">
          AI 판단 근거: {extra.top_factors.map((f) => f.label).join(', ')} (위험 점수{' '}
          {Math.round(extra.ml_score * 100)}점)
        </p>
      )}
    </div>
  )
}
