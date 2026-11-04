import { useEffect, useState } from 'react'

import { api } from '../api/client'

interface DemoStatus {
  demo_mode: boolean
  now_kst: string
  shifted: boolean
}

/** 시연 모드에서 업무 시각을 옮겼을 때(예: 새벽 2시) 화면 위에 보여 준다. 평소에는 아무것도 그리지 않는다. */
export default function DemoClockBadge() {
  const [status, setStatus] = useState<DemoStatus | null>(null)

  useEffect(() => {
    let alive = true
    const load = () =>
      api<DemoStatus>('/demo/status').then(
        (s) => alive && setStatus(s),
        () => alive && setStatus(null),
      )
    load()
    const timer = window.setInterval(load, 15_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  if (!status?.demo_mode || !status.shifted) return null
  const time = new Date(status.now_kst).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit' })
  return (
    <div className="demo-clock" role="status">
      🕑 시연 시각 {time}
    </div>
  )
}
