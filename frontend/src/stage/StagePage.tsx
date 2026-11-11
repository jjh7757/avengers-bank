import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { CreditCard, Landmark, MessageCircle, Settings, ShieldAlert, ShoppingBag } from 'lucide-react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api/client'
import { chatApi } from '../api/endpoints'
import type { AccountType, CardType, ChatMessage, ProductKind, Screen, SignupPrefill, UiContext, UiSelected } from '../api/types'
import { useAuth } from '../auth/useAuth'
import Logo from '../components/Logo'
import TransferCard, { type Status } from '../components/TransferCard'
import { useChatSession } from '../hooks/useChatSession'
import Mascot, { type Mood } from './Mascot'
import {
  AccountPanel,
  AccountsPanel,
  CardPanel,
  CardsPanel,
  FdsPanel,
  HomePanel,
  ProductsPanel,
  SignupPanel,
  type ProductFilter,
} from './panels'
import { selectionKey, type Pick } from './selection'
import './stage.css'

/**
 * 첫 화면(/): 채팅 목록 대신 캐릭터 "모아"가 필요한 화면을 무대로 끌어온다.
 * 채팅 화면(/chat)과 같은 대화 세션·API를 쓰고, 어떤 화면을 가져올지는 답변의 screen(백엔드가 쓴 도구로 정함)을 따른다.
 */

const SUGGESTIONS = ['내 잔액 알려줘', '엄마한테 5만원 보내줘', '내 카드 보여줘', '적금 상품 추천해줘']
const GREETING = '안녕하세요, 저는 모아예요. 필요한 화면을 가져다 드릴게요.'
const BRING_MS = 800 // 끌어오기 애니메이션(0.75초)이 끝나고 버튼 잠금을 푸는 시점

interface View {
  screen: Screen
  msgId: number | null // transfer 화면이면 확인 카드가 담긴 메시지
  params?: Record<string, unknown> // 모아가 아니라 사용자가 연 화면의 대상 (상품 화면의 "가입하기")
  key: number // 바뀔 때마다 패널을 다시 마운트해 끌어오기 연출과 최신 데이터 불러오기
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

const ACCOUNT_TYPES: AccountType[] = ['checking', 'deposit', 'savings']
const CARD_TYPES: CardType[] = ['credit', 'debit']
const PRODUCT_KINDS = ['account', 'card', 'all'] as const
const PREFILL_KEYS = ['term_months', 'monthly_payment', 'monthly_deposit_date', 'checking_account_id', 'payment_date'] as const

/** 답변의 screen_params(서버가 도구 인자로 채운 값)를 화면별 대상으로. 모양이 맞지 않으면 목록 화면을 보여 준다 */
function screenTarget(params: Record<string, unknown>) {
  const { account_type, account_id, card_type, card_id, kind, keyword, product_id } = params
  return {
    account:
      ACCOUNT_TYPES.includes(account_type as AccountType) && typeof account_id === 'number'
        ? { type: account_type as AccountType, id: account_id }
        : null,
    card:
      CARD_TYPES.includes(card_type as CardType) && typeof card_id === 'number'
        ? { type: card_type as CardType, id: card_id }
        : null,
    signup:
      (kind === 'account' || kind === 'card') && typeof product_id === 'number'
        ? {
            kind: kind as ProductKind,
            productId: product_id,
            prefill: Object.fromEntries(
              PREFILL_KEYS.filter((k) => typeof params[k] === 'number').map((k) => [k, params[k]]),
            ) as SignupPrefill,
          }
        : null,
    products: {
      kind: PRODUCT_KINDS.find((k) => k === kind),
      keyword: typeof keyword === 'string' ? keyword : undefined,
      productId: typeof product_id === 'number' ? product_id : undefined,
    } satisfies ProductFilter,
  }
}

/** 새로고침하면 마지막으로 화면을 가져온 답변의 화면을 연출 없이 보여 준다 */
function restoredView(messages: ChatMessage[]): View {
  const last = messages.findLast((m) => m.role === 'assistant' && m.screen)
  return last?.screen ? { screen: last.screen, msgId: last.msg_id, key: 0 } : { screen: 'home', msgId: null, key: 0 }
}

export default function StagePage() {
  const { user } = useAuth()
  const { sessionId, messages, setMessages, error, setError, startNewSession } = useChatSession()
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [mood, setMood] = useState<Mood>('idle')
  const [view, setView] = useState<View | null>(null) // null이면 대화 기록에서 복원
  const [arriving, setArriving] = useState(false)
  const [bubble, setBubble] = useState<string | null>(null) // null이면 마지막 답변
  const [pendingText, setPendingText] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const [selected, setSelected] = useState<UiSelected | null>(null) // 눌러서 고른 항목 ("이거")
  const panelRef = useRef<HTMLElement>(null)
  const timers = useRef<number[]>([])
  const requestRef = useRef(0) // 새 요청이 오면 이전 요청의 늦게 끝난 콜백은 무시한다

  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  const later = (ms: number, fn: () => void) => {
    timers.current.push(window.setTimeout(fn, reducedMotion() ? Math.min(ms, 150) : ms))
  }

  const shown = view ?? restoredView(messages)
  const lastAssistant = messages.findLast((m) => m.role === 'assistant')
  const lastUser = messages.findLast((m) => m.role === 'user')
  const lastCardId = messages.findLast((m) => m.card?.type === 'transfer_confirmation')?.msg_id
  const shownMessage = shown.msgId != null ? messages.find((m) => m.msg_id === shown.msgId) : undefined
  const transferMessage = shown.screen === 'transfer' ? shownMessage : undefined
  const shownParams = shown.params ?? shownMessage?.screen_params ?? {}
  const target = screenTarget(shownParams)
  const bubbleText = bubble ?? lastAssistant?.content ?? GREETING

  const pick: Pick = {
    selectedKey: selected && selectionKey(selected),
    onSelect: (item) => {
      const same = selected && selectionKey(selected) === selectionKey(item)
      setSelected(same ? null : item)
      setBubble(same ? null : `"${item.label}" 골랐어요. 무엇을 도와드릴까요?`)
    },
  }

  /** 지금 보고 있는 화면. "이거", "이 계좌", "두 번째 거"를 에이전트가 풀 수 있게 메시지와 함께 보낸다 */
  function currentUi(): UiContext {
    // 화면에 보이는 항목은 패널이 data-ui-label로 표시해 둔 것을 위에서부터 모은다
    const labels = [...(panelRef.current?.querySelectorAll<HTMLElement>('[data-ui-label]') ?? [])]
      .map((element) => (element.dataset.uiLabel ?? '').slice(0, 60))
      .filter(Boolean)
      .slice(0, 10)
    return {
      screen: shown.screen,
      screen_params: shownParams,
      selected: selected && { ...selected, label: selected.label.slice(0, 60) },
      visible: labels,
    }
  }

  /** 답변을 말풍선에 띄운다. 말하는 표정은 글 길이만큼 보여 준다 */
  function talk(message: ChatMessage, request: number) {
    setBubble(null)
    setMood('speaking')
    later(Math.min(3500, Math.max(1200, message.content.length * 60)), () => {
      if (requestRef.current === request) setMood((m) => (m === 'speaking' ? 'idle' : m))
    })
  }

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || !sessionId || busy) return
    const request = ++requestRef.current
    const ui = currentUi()
    timers.current.forEach(clearTimeout)
    timers.current = []
    setBusy(true)
    setError(null)
    setInput('')
    setPendingText(trimmed)
    setArriving(true) // 답을 기다리는 동안 지금 화면(예: 지난 확인 카드)을 잠근다
    setBubble('')
    setMood('thinking')
    try {
      const { user_message, assistant_message } = await chatApi.send(sessionId, trimmed, ui)
      if (requestRef.current !== request) return
      setMessages((prev) => [...prev, user_message, assistant_message])
      setPendingText(null)
      const screen = assistant_message.screen
      if (screen) {
        setSelected(null) // 새 화면이 오면 고른 항목은 풀린다
        setMood('bringing')
        setView((v) => ({ screen, msgId: assistant_message.msg_id, key: (v?.key ?? 0) + 1 }))
        later(BRING_MS, () => {
          setArriving(false)
          talk(assistant_message, request)
        })
      } else {
        setArriving(false)
        talk(assistant_message, request)
      }
    } catch (e) {
      setPendingText(null)
      setArriving(false)
      setInput(trimmed)
      setMood('worried')
      setBubble(e instanceof ApiError ? e.message : '보내지 못했어요. 잠시 후 다시 해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  /** 이체 확인 카드의 진행 상황에 따라 모아의 표정과 말을 바꾼다 */
  const onTransferStatus = useCallback((kind: Status['kind']) => {
    switch (kind) {
      case 'sending':
        setMood('thinking')
        break
      case 'need_pin':
        setMood('worried')
        setBubble('평소와 다른 이체라서 한 번 더 확인할게요. 이체 PIN을 입력해 주세요.')
        break
      case 'blocked':
        setMood('worried')
        setBubble('잠깐만요! 사기가 의심돼서 이체를 멈췄어요. 화면의 경고를 꼭 읽어 주세요.')
        break
      case 'done':
        setMood('idle')
        setBubble('보냈어요!')
        break
      case 'error':
        setMood('worried')
        break
    }
  }, [])

  /** 상품 화면의 "가입하기": 모아에게 말하지 않고 바로 가입 화면을 무대로 */
  function openSignup(kind: ProductKind, productId: number) {
    setSelected(null)
    setView((v) => ({ screen: 'signup', msgId: null, params: { kind, product_id: productId }, key: (v?.key ?? 0) + 1 }))
    setBubble('이용약관을 읽고 동의한 다음, 가입 조건을 채우고 "가입하기"를 눌러 주세요.')
  }

  async function newConversation() {
    requestRef.current++
    timers.current.forEach(clearTimeout)
    await startNewSession()
    setView(null)
    setBubble(null)
    setSelected(null)
    setMood('idle')
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(input)
  }

  const userLine = pendingText ?? lastUser?.content
  const shownMood: Mood = mood

  return (
    <div className="stage-app">
      <header className="stage-header">
        <Logo className="stage-brand" size={26} />
        <span className="stage-header-actions">
          <button className="button small" onClick={newConversation} disabled={busy}>
            새 대화
          </button>
          <button className="button small" onClick={() => setShowLog((v) => !v)} aria-expanded={showLog}>
            <span className="stage-wide-only">대화 </span>기록
          </button>
          <button className="button small" onClick={() => setShowMenu((v) => !v)} aria-expanded={showMenu}>
            메뉴
          </button>
        </span>
        {showMenu && (
          <nav className="stage-menu" aria-label="전체 메뉴">
            {MENU.map((item) => (
              <Link key={item.to} to={item.to}>
                <item.icon size={20} aria-hidden="true" /> {item.label}
              </Link>
            ))}
          </nav>
        )}
      </header>

      <div className="stage-body">
        <aside className="stage-helper">
          <div className="stage-bubble" aria-live="polite">
            {bubbleText || (
              <span className="typing-dots" aria-label="찾는 중">
                •••
              </span>
            )}
          </div>
          <Mascot mood={shownMood} />
          <p className="stage-mood muted small">{MOOD_LABEL[shownMood]}</p>
        </aside>

        <main className="stage-floor">
          {userLine && <p className="stage-user-line">나: {userLine}</p>}
          <section
            key={shown.key}
            ref={panelRef}
            className={`stage-panel ${shown.key ? 'arrive' : ''} panel-${transferMessage ? 'transfer' : shown.screen}`}
            inert={arriving || busy}
            aria-busy={arriving || busy}
          >
            {shown.key > 0 && <span className="stage-grip" aria-hidden="true" />}
            {(shown.screen === 'accounts' || (shown.screen === 'account' && !target.account)) && <AccountsPanel pick={pick} />}
            {shown.screen === 'account' && target.account && <AccountPanel {...target.account} />}
            {(shown.screen === 'cards' || (shown.screen === 'card' && !target.card)) && <CardsPanel pick={pick} />}
            {shown.screen === 'card' && target.card && <CardPanel {...target.card} />}
            {shown.screen === 'products' && (
              <ProductsPanel reply={shownMessage?.content ?? ''} pick={pick} onSignup={openSignup} {...target.products} />
            )}
            {shown.screen === 'signup' && target.signup && (
              <SignupPanel
                key={`${target.signup.kind}-${target.signup.productId}`}
                {...target.signup}
                onDone={() => {
                  setMood('idle')
                  setBubble('가입했어요! 화면에서 새 계좌·카드를 확인해 보세요.')
                }}
              />
            )}
            {shown.screen === 'signup' && !target.signup && <ProductsPanel reply="" pick={pick} onSignup={openSignup} />}
            {shown.screen === 'fds' && <FdsPanel />}
            {shown.screen === 'transfer' && transferMessage?.card?.type === 'transfer_confirmation' && sessionId ? (
              <TransferCard
                card={transferMessage.card}
                sessionId={sessionId}
                active={transferMessage.msg_id === lastCardId}
                onCancel={() => send('이체 취소')}
                onStatusChange={onTransferStatus}
              />
            ) : (
              (shown.screen === 'home' || shown.screen === 'transfer') && <HomePanel name={user?.name} />
            )}
          </section>
          {error && (
            <p className="error center" role="alert">
              {error}
            </p>
          )}
        </main>
      </div>

      {showLog && (
        <div className="stage-log" role="log">
          {messages.length === 0 && <p className="muted small">아직 대화가 없어요.</p>}
          {messages.map((m) => (
            <p key={m.msg_id} className={`stage-log-line ${m.role}`}>
              <strong>{m.role === 'user' ? '나' : '모아'}</strong> 
              {m.content}
            </p>
          ))}
        </div>
      )}

      <footer className="stage-footer">
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => send(s)} disabled={busy || !sessionId}>
              {s}
            </button>
          ))}
        </div>
        <form className="stage-composer" onSubmit={submit}>
          <input
            className="stage-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="모아에게 말해 보세요"
            maxLength={1000}
            aria-label="메시지"
          />
          <button className="button primary" disabled={!input.trim() || busy || !sessionId}>
            보내기
          </button>
        </form>
      </footer>
    </div>
  )
}

/** 모아에게 말하지 않고 직접 가고 싶을 때 (기존 화면들) */
const MENU = [
  { to: '/chat', label: '대화 기록 (채팅으로 보기)', icon: MessageCircle },
  { to: '/accounts', label: '내 계좌', icon: Landmark },
  { to: '/cards', label: '내 카드', icon: CreditCard },
  { to: '/products', label: '상품 보기·가입', icon: ShoppingBag },
  { to: '/fds', label: '이상거래 기록', icon: ShieldAlert },
  { to: '/settings', label: '설정 (PIN 등록)', icon: Settings },
]

const MOOD_LABEL: Record<Mood, string> = {
  idle: '모아',
  listening: '듣는 중',
  thinking: '찾는 중',
  speaking: '말하는 중',
  bringing: '화면 가져오는 중',
  worried: '주의!',
}
