import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Mic } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { chatApi } from '../api/endpoints'
import { useAuth } from '../auth/useAuth'
import Logo from '../components/Logo'
import AccountSummaryCardView from '../components/AccountSummaryCardView'
import TransferCard from '../components/TransferCard'
import { useChatSession } from '../hooks/useChatSession'
import { usePushToTalk } from '../hooks/usePushToTalk'
import { useSpeech } from '../hooks/useSpeech'

const SUGGESTIONS = ['내 잔액 알려줘', '엄마한테 5만원 보내줘', '적금 상품 추천해줘']

export default function ChatPage() {
  const { user } = useAuth()
  const speech = useSpeech()
  const { sessionId, messages, setMessages, error, setError, startNewSession } = useChatSession()
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [voicePrompt, setVoicePrompt] = useState<string | null>(null)
  const [autoVoiceFor, setAutoVoiceFor] = useState<number | null>(null) // 안내를 다 읽고 음성 승인 녹음을 시작할 카드
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, busy])

  const send = useCallback(
    async (text: string, inputMode: 'text' | 'voice') => {
      const trimmed = text.trim()
      if (!trimmed || !sessionId || busy) return
      setBusy(true)
      setError(null)
      setInput('')
      setVoicePrompt(null)
      try {
        const { user_message, assistant_message } = await chatApi.send(sessionId, trimmed, inputMode)
        setMessages((prev) => [...prev, user_message, assistant_message])
        const card = assistant_message.card
        if (card?.type === 'transfer_confirmation') {
          const reads = speech.ttsAvailable && speech.ttsEnabled
          speech.speak(card.tts_text).then(() => {
            // "확인 사 칠 이 라고 말씀해 주세요"를 들려준 뒤에만 자동으로 녹음한다 (안내가 꺼져 있으면 버튼으로)
            if (reads && card.voice_challenge) setAutoVoiceFor(assistant_message.msg_id)
          })
        } else {
          speech.speak(assistant_message.content)
        }
      } catch (e) {
        setInput(trimmed)
        setError(e instanceof ApiError ? e.message : '보내지 못했어요.')
      } finally {
        setBusy(false)
      }
    },
    [sessionId, busy, speech, setMessages, setError],
  )
  const ptt = usePushToTalk({ speech, busy, send, setInput, setVoicePrompt })

  function submit(event: FormEvent) {
    event.preventDefault()
    send(input, 'text')
  }

  const lastCardIndex = messages.findLastIndex((m) => m.card?.type === 'transfer_confirmation')
  const ttsLabel = !speech.voicesLoaded ? '음성 확인 중' : speech.ttsAvailable ? (speech.ttsEnabled ? '음성 켬' : '음성 끔') : '음성 불가'

  return (
    <section className="chat">
      <header className="chat-header">
        <h1><Logo size={26} /></h1>
        <div className="chat-header-actions">
          <button
            className={`toggle ${speech.ttsEnabled && speech.ttsAvailable ? 'on' : ''}`}
            onClick={() => speech.setTtsEnabled(!speech.ttsEnabled)}
            disabled={!speech.ttsAvailable}
            aria-pressed={speech.ttsEnabled}
            aria-label="음성 안내"
            title={speech.ttsAvailable ? '답변을 소리로 읽어 줍니다' : '이 브라우저에는 한국어 음성이 없어요'}
          >
            {ttsLabel}
          </button>
          <button className="button small" onClick={() => startNewSession()} disabled={busy}>
            새 대화
          </button>
          <Link className="button small" to="/">
            모아 화면
          </Link>
        </div>
      </header>
      {speech.voicesLoaded && !speech.ttsAvailable && (
        <p className="notice">이 브라우저에는 한국어 음성이 없어 답변을 소리로 읽을 수 없어요. Chrome을 권장해요.</p>
      )}

      <div className="messages" aria-live="polite">
        {messages.length === 0 && !busy && (
          <div className="welcome">
            <p>
              <strong>{user?.name}</strong>님, 무엇을 도와드릴까요?
            </p>
            <p className="muted">마이크 버튼을 누른 채로 말하거나 글로 써 주세요.</p>
            <div className="chips">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s, 'text')}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, index) => (
          <div key={m.msg_id} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>
              {m.role === 'user' && m.input_mode === 'voice' && <Mic size={14} aria-hidden="true" className="inline-icon voice-tag" />}
              {m.content}
            </div>
            {m.card?.type === 'transfer_confirmation' && sessionId && (
              <TransferCard
                card={m.card}
                sessionId={sessionId}
                inputMode={messages[index - 1]?.input_mode ?? 'text'}
                active={index === lastCardIndex}
                autoVoice={autoVoiceFor === m.msg_id}
                speech={speech}
                onCancel={() => send('이체 취소', 'text')}
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

      {(voicePrompt || speech.listening) && (
        <p className="voice-prompt" role="status">
          {speech.listening ? `듣는 중… ${speech.interim}` : voicePrompt}
        </p>
      )}

      <form className="composer" onSubmit={submit}>
        <button
          type="button"
          className={`mic ${speech.listening ? 'listening' : ''}`}
          onPointerDown={ptt.onMicDown}
          onPointerUp={ptt.onMicUp}
          onPointerLeave={ptt.onMicUp}
          disabled={!speech.sttSupported || busy}
          aria-label={speech.sttSupported ? '누르고 있는 동안 말하기' : '이 브라우저는 음성 입력을 지원하지 않아요'}
          title={speech.sttSupported ? '누르고 있는 동안 말하기' : '음성 입력은 Chrome·Edge에서 쓸 수 있어요'}
        >
          <Mic size={24} aria-hidden="true" />
        </button>
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
