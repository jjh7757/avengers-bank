import { useCallback, useEffect, useState } from 'react'

import { chatApi } from '../api/endpoints'
import type { ChatMessage } from '../api/types'
import { useAuth } from '../auth/useAuth'

function sessionKey(userId: number) {
  return `avengers.chat_session.${userId}`
}

/**
 * 대화 세션: 새로고침해도 같은 대화를 이어 간다 (탭을 닫으면 새 대화).
 * 채팅 화면(/)과 도우미 화면(/stage)이 같은 세션을 쓴다.
 */
export function useChatSession() {
  const { user } = useAuth()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [error, setError] = useState<string | null>(null)

  const startNewSession = useCallback(async () => {
    const { session_id } = await chatApi.createSession()
    try {
      sessionStorage.setItem(sessionKey(user!.user_id), session_id)
    } catch {
      /* 저장 못 하면 새로고침 때 새 대화 */
    }
    setSessionId(session_id)
    setMessages([])
  }, [user])

  useEffect(() => {
    let saved: string | null = null
    try {
      saved = sessionStorage.getItem(sessionKey(user!.user_id))
    } catch {
      saved = null
    }
    if (!saved) {
      startNewSession().catch(() => setError('대화를 시작하지 못했어요.'))
      return
    }
    chatApi
      .messages(saved)
      .then((loaded) => {
        setSessionId(saved)
        setMessages(loaded)
      })
      .catch(() => startNewSession().catch(() => setError('대화를 시작하지 못했어요.')))
  }, [user, startNewSession])

  return { sessionId, messages, setMessages, error, setError, startNewSession }
}
