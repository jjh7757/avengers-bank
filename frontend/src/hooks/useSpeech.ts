/**
 * 브라우저 Web Speech API 래퍼 (PROJECT_PLAN.md 3.5)
 * - STT: SpeechRecognition(ko-KR). 마이크 버튼을 누르는 동안 듣기(push-to-talk) + "확인" 대답 한 번 듣기
 * - TTS: SpeechSynthesis(ko-KR 보이스). 기본 켜짐, 끄더라도 FDS 경고는 force로 읽는다
 */
import { useCallback, useEffect, useRef, useState } from 'react'

interface RecognitionResultEvent {
  resultIndex: number
  results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>
}

interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event: RecognitionResultEvent) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

type RecognitionConstructor = new () => Recognition

function recognitionConstructor(): RecognitionConstructor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

const TTS_KEY = 'avengers.tts_enabled'

function loadTtsSetting(): boolean {
  try {
    return localStorage.getItem(TTS_KEY) !== 'off' // 기본 켜짐
  } catch {
    return true
  }
}

export function useSpeech() {
  const Ctor = recognitionConstructor()
  const sttSupported = Ctor !== null
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const recognitionRef = useRef<Recognition | null>(null)

  const ttsSupported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [koVoice, setKoVoice] = useState<SpeechSynthesisVoice | null>(null)
  const [voicesLoaded, setVoicesLoaded] = useState(!ttsSupported)
  const [ttsEnabled, setTtsEnabledState] = useState(loadTtsSetting)
  const [speaking, setSpeaking] = useState(false)

  // 보이스 목록은 비동기로 채워진다
  useEffect(() => {
    if (!ttsSupported) return
    const pick = () => {
      const voices = speechSynthesis.getVoices()
      if (voices.length) {
        setKoVoice(voices.find((v) => v.lang.toLowerCase().startsWith('ko')) ?? null)
        setVoicesLoaded(true)
      }
    }
    pick()
    speechSynthesis.addEventListener('voiceschanged', pick)
    const timer = window.setTimeout(() => setVoicesLoaded(true), 2000) // 보이스가 끝내 없을 때
    return () => {
      speechSynthesis.removeEventListener('voiceschanged', pick)
      window.clearTimeout(timer)
    }
  }, [ttsSupported])

  const ttsAvailable = ttsSupported && koVoice !== null

  const setTtsEnabled = useCallback((on: boolean) => {
    setTtsEnabledState(on)
    try {
      localStorage.setItem(TTS_KEY, on ? 'on' : 'off')
    } catch {
      /* 저장 못 해도 이번 화면에서는 적용 */
    }
  }, [])

  const cancelSpeech = useCallback(() => {
    if (ttsSupported) speechSynthesis.cancel()
    setSpeaking(false)
  }, [ttsSupported])

  /** 읽기가 끝나면 resolve. force면 토글이 꺼져 있어도 읽는다 (FDS 경고). */
  const speak = useCallback(
    (text: string, options: { force?: boolean } = {}) =>
      new Promise<void>((resolve) => {
        if (!ttsAvailable || (!ttsEnabled && !options.force) || !text) {
          resolve()
          return
        }
        speechSynthesis.cancel()
        const utterance = new SpeechSynthesisUtterance(text)
        utterance.voice = koVoice
        utterance.lang = koVoice?.lang ?? 'ko-KR'
        utterance.rate = 0.95
        utterance.onend = utterance.onerror = () => {
          setSpeaking(false)
          resolve()
        }
        setSpeaking(true)
        speechSynthesis.speak(utterance)
      }),
    [ttsAvailable, ttsEnabled, koVoice],
  )

  /** 내부 공통: 인식을 시작하고, 끝나면 최종 문장을 돌려준다 */
  const recognize = useCallback(
    (onInterim?: (text: string) => void, timeoutMs?: number) =>
      new Promise<string>((resolve) => {
        if (!Ctor) {
          resolve('')
          return
        }
        recognitionRef.current?.abort()
        const recognition = new Ctor()
        recognition.lang = 'ko-KR'
        recognition.interimResults = true
        recognition.continuous = true
        let finalText = ''
        let timer: number | undefined
        recognition.onresult = (event) => {
          let partial = ''
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const result = event.results[i]
            if (result.isFinal) finalText += result[0].transcript
            else partial += result[0].transcript
          }
          onInterim?.((finalText + partial).trim())
        }
        recognition.onerror = () => recognition.stop()
        recognition.onend = () => {
          window.clearTimeout(timer)
          recognitionRef.current = null
          setListening(false)
          setInterim('')
          resolve(finalText.trim())
        }
        recognitionRef.current = recognition
        setListening(true)
        recognition.start()
        if (timeoutMs) timer = window.setTimeout(() => recognition.stop(), timeoutMs)
      }),
    [Ctor],
  )

  /** 마이크 버튼을 누를 때 시작. 손을 떼면 stopListening() → 이 Promise가 최종 문장으로 끝난다. */
  const startListening = useCallback(() => {
    cancelSpeech() // 마이크를 누르면 읽던 안내는 멈춘다
    return recognize(setInterim)
  }, [cancelSpeech, recognize])

  const stopListening = useCallback(() => recognitionRef.current?.stop(), [])

  /** 질문 뒤 대답 한 번 듣기 ("확인" / "아니"). 말이 없으면 timeout 뒤 빈 문자열. */
  const listenOnce = useCallback((timeoutMs = 5000) => recognize(setInterim, timeoutMs), [recognize])

  useEffect(
    () => () => {
      recognitionRef.current?.abort()
      if (ttsSupported) speechSynthesis.cancel()
    },
    [ttsSupported],
  )

  return {
    sttSupported,
    listening,
    interim,
    startListening,
    stopListening,
    listenOnce,
    ttsAvailable,
    voicesLoaded,
    ttsEnabled,
    setTtsEnabled,
    speaking,
    speak,
    cancelSpeech,
  }
}

export type Speech = ReturnType<typeof useSpeech>
