import { Clock } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { useAuth } from '../auth/useAuth'

export const IDLE_LIMIT_MS = 10 * 60 * 1000 // 10분 동안 아무것도 안 하면 로그아웃
const WARN_BEFORE_MS = 60 * 1000 // 1분 전에 미리 알린다
const ACTIVITY_KEY = 'avengers.last_activity' // 다른 탭에서 쓰고 있으면 이 탭도 유지
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

function readShared(): number {
  try {
    return Number(localStorage.getItem(ACTIVITY_KEY)) || 0
  } catch {
    return 0
  }
}

function writeShared(time: number) {
  try {
    localStorage.setItem(ACTIVITY_KEY, String(time))
  } catch {
    /* 저장소를 못 쓰면 이 탭 기준으로만 잰다 */
  }
}

/**
 * 자동 로그아웃 (금융 앱 기본 보안). 10분 동안 조작이 없으면 1분 전에 알리고, 그래도 없으면 로그아웃한다.
 * 컴퓨터가 잠들었다 깨어나도 지난 시간을 다시 재서 바로 판단한다.
 */
export default function IdleGuard() {
  const { user, logout } = useAuth()
  const lastActivity = useRef(0) // 로그인하면 아래 effect가 지금 시각으로 맞춘다
  const lastWrite = useRef(0)
  const [remaining, setRemaining] = useState<number | null>(null) // 경고 중이면 남은 초
  const warning = useRef(false)

  const touch = useCallback(() => {
    const now = Date.now()
    lastActivity.current = now
    if (now - lastWrite.current > 5000) {
      lastWrite.current = now
      writeShared(now)
    }
  }, [])

  const extend = useCallback(() => {
    touch()
    writeShared(Date.now())
    warning.current = false
    setRemaining(null)
  }, [touch])

  useEffect(() => {
    if (!user) return
    lastActivity.current = Date.now()
    writeShared(lastActivity.current)

    const onActivity = () => {
      // 경고가 떠 있으면 "계속 이용하기"를 눌러야 연장된다 (자리를 비운 사이 우연한 입력으로 연장되지 않게)
      if (!warning.current) touch()
    }
    ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, onActivity, { passive: true }))

    const check = () => {
      const last = Math.max(lastActivity.current, readShared())
      const left = IDLE_LIMIT_MS - (Date.now() - last)
      warning.current = left > 0 && left <= WARN_BEFORE_MS
      if (left <= 0) {
        setRemaining(null)
        logout('idle')
      } else if (warning.current) {
        setRemaining(Math.ceil(left / 1000))
      } else {
        setRemaining(null) // 다른 탭에서 연장했으면 경고를 내린다
      }
    }
    const timer = window.setInterval(check, 1000)
    document.addEventListener('visibilitychange', check)
    return () => {
      ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, onActivity))
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', check)
    }
  }, [user, logout, touch])

  if (!user || remaining === null) return null
  return (
    <div className="idle-backdrop">
      <div className="idle-dialog" role="alertdialog" aria-modal="true" aria-labelledby="idle-title" aria-describedby="idle-desc">
        <span className="idle-icon" aria-hidden="true">
          <Clock size={28} />
        </span>
        <p id="idle-title" className="idle-title">
          곧 자동으로 로그아웃돼요
        </p>
        <p id="idle-desc" className="muted">
          10분 동안 사용하지 않아 <strong className="idle-count">{remaining}초</strong> 뒤 안전을 위해 로그아웃해요.
        </p>
        <div className="button-row">
          <button className="button" onClick={() => logout('user')}>
            로그아웃
          </button>
          <button className="button primary" onClick={extend} autoFocus>
            계속 이용하기
          </button>
        </div>
      </div>
    </div>
  )
}
