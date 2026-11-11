import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { chatApi } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'
import Logo from '../components/Logo'
import AccountSummaryCardView from '../components/AccountSummaryCardView'
import TransferCard from '../components/TransferCard'
import { useChatSession } from '../hooks/useChatSession'

const SUGGESTIONS = ['내 잔액 알려줘', '엄마한테 5만원 보내줘', '적금 상품 추천해줘']

export default function ChatPage() {
  const { user } = useAuth()
  const { sessionId, messages, setMessages, error, setError, startNewSession } = useChatSession()
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || !sessionId || busy) return
      setBusy(true)
      setError(null)
      setInput('')
      try {
        const { user_message, assistant_message } = await chatApi.send(sessionId, trimmed)
        setMessages((prev) => [...prev, user_message, assistant_message])
      } catch (e) {
        setInput(trimmed)
        setError(e instanceof ApiError ? e.message : '보내지 못했어요.')
      } finally {
        setBusy(false)
      }
    },
    [sessionId, busy, setMessages, setError],
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    send(input)
  }

  const lastCardIndex = messages.findLastIndex((m) => m.card?.type === 'transfer_confirmation')

  return (
    <section className="chat">
      <header className="chat-header">
        <h1><Logo size={26} /></h1>
        <div className="chat-header-actions">
          <button className="button small" onClick={() => startNewSession()} disabled={busy}>
            새 대화
          </button>
          <Link className="button small" to="/">
            모아 화면
          </Link>
        </div>
      </header>

      <div className="messages" aria-live="polite">
        {messages.length === 0 && !busy && (
          <div className="welcome">
            <p>
              <strong>{user?.name}</strong>님, 무엇을 도와드릴까요?
            </p>
            <p className="muted">하고 싶은 일을 글로 써 주세요.</p>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, index) => (
          <div key={m.msg_id} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>
              {m.content}
            </div>
            {m.card?.type === 'transfer_confirmation' && sessionId && (
              <TransferCard
                card={m.card}
                sessionId={sessionId}
                active={index === lastCardIndex}
                onCancel={() => send('이체 취소')}
              />
            )}
            {m.card?.type === 'account_summary' && <AccountSummaryCardView card={m.card} />}
          </div>
        ))}
        {busy && (
          <div className="bubble-row assistant">
            <div className="bubble assistant typing">답변을 준비하고 있어요…</div>
          </div>
        )}
        {error && (
          <p className="error center" role="alert">
            {error}
          </p>
        )}
        <div ref={bottomRef} />
      </div>

      <form className="composer" onSubmit={submit}>
        <input
          className="composer-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="예: 엄마한테 5만원 보내줘"
          maxLength={1000}
          aria-label="메시지"
        />
        <button className="button primary" disabled={!input.trim() || busy || !sessionId}>
          보내기
        </button>
      </form>
    </section>
  )
}
