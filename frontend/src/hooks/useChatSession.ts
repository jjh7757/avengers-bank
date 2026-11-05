import { useCallback, useEffect, useRef, useState } from 'react'

import { chatApi } from '../api/endpoints'
import type { ChatMessage } from '../api/types'
import { useAuth } from '../auth/useAuth'

function sessionKey(userId: number) {
  return `avengers.chat_session.${userId}`
}

/**
 * 대화 세션: 새로고침해도 같은 대화를 이어 간다 (탭을 닫으면 새 대화).
 * 도우미 화면(/)과 채팅 화면(/chat)이 같은 세션을 쓴다.
 */
export function useChatSession() {
  const { user } = useAuth()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [error, setError] = useState<string | null>(null)
  const latestRequest = useRef(0)

  /**
   * 새 세션을 만드는 동안은 sessionId를 비워 둔다 (화면의 send()는 sessionId가 없으면 보내지 않는다).
   * 이전 세션 ID를 남겨 두면 "새 대화"를 누르자마자 보낸 첫 메시지가 이전 세션에 저장되고,
   * FDS 대화 판별(세션 단위)이 그 메시지를 보지 못한다.
   * 여러 번 눌렀을 때는 마지막 요청의 세션만 쓴다.
   */
  const createSession = useCallback(async () => {
    const request = ++latestRequest.current
    let sessionId: string
    try {
      sessionId = (await chatApi.createSession()).session_id
    } catch {
      if (request === latestRequest.current) setError('대화를 시작하지 못했어요.')
      return
    }
    if (request !== latestRequest.current) return
    try {
      sessionStorage.setItem(sessionKey(user!.user_id), sessionId)
    } catch {
      /* 저장 못 하면 새로고침 때 새 대화 */
    }
    setSessionId(sessionId)
  }, [user])

  const startNewSession = useCallback(async () => {
    setSessionId(null)
    setMessages([])
    setError(null)
    await createSession()
  }, [createSession])

  useEffect(() => {
    let saved: string | null = null
    try {
      saved = sessionStorage.getItem(sessionKey(user!.user_id))
    } catch {
      saved = null
    }
    if (!saved) {
      createSession() // 처음 열 때는 sessionId·messages가 이미 비어 있다
      return
    }
    const request = latestRequest.current
    chatApi
      .messages(saved)
      .then((loaded) => {
        if (request !== latestRequest.current) return // 불러오는 사이에 "새 대화"를 눌렀다
        setSessionId(saved)
        setMessages(loaded)
      })
      .catch(() => {
        if (request === latestRequest.current) createSession()
      })
  }, [user, createSession])

  return { sessionId, messages, setMessages, error, setError, startNewSession }
}
