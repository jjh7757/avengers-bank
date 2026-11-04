import { useCallback } from 'react'
import { Link } from 'react-router-dom'

import { fdsApi } from '../api/endpoints'
import { useLoad } from '../hooks/useLoad'
import { dateTime, won, FDS_DECISION_LABEL } from '../lib/format'

/** FDS 판정 기록 (발표용 대시보드) */
export default function FdsLogsPage() {
  const { data: logs, error, loading } = useLoad(useCallback(() => fdsApi.logs(), []))

  return (
    <section className="page wide">
      <Link to="/settings" className="back">
        ← 설정
      </Link>
      <h1>이상거래 탐지 기록</h1>
      {loading && <p className="muted">불러오는 중…</p>}
      {error && <p className="error">{error}</p>}
      {logs && logs.length === 0 && <p className="muted">아직 기록이 없어요.</p>}
      {logs && logs.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>시각</th>
                <th>금액</th>
                <th>등급</th>
                <th>결과</th>
                <th>걸린 규칙</th>
                <th>ML 점수</th>
                <th>주요 요인</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.fds_log_id}>
                  <td>{dateTime(log.created_at)}</td>
                  <td className="num">{won(log.amount)}</td>
                  <td>
                    <span className={`risk risk-${log.risk_level.toLowerCase()}`}>{log.risk_level}</span>
                  </td>
                  <td>{FDS_DECISION_LABEL[log.decision] ?? log.decision}</td>
                  <td>{log.rule_hits.map((h) => h.name).join(', ') || '-'}</td>
                  <td className="num">{log.ml_score?.toFixed(3) ?? '-'}</td>
                  <td>{log.top_factors.map((f) => f.label).join(', ') || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
