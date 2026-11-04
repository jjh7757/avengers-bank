import { useRef } from 'react'

import type { Speech } from './useSpeech'

const YES = /확인/
const NO = /아니|취소|틀렸|다시/

interface Options {
  speech: Speech
  busy: boolean
  send: (text: string, inputMode: 'text' | 'voice') => Promise<void>
  setInput: (text: string) => void
  setVoicePrompt: (text: string | null) => void // 화면에 띄우는 음성 안내 (보낼 때 화면이 지운다)
}

/** 마이크를 누르고 있는 동안 듣고, 손을 떼면 인식한 문장을 되읽어 "확인"이라고 하면 보낸다. */
export function usePushToTalk({ speech, busy, send, setInput, setVoicePrompt }: Options) {
  const pushingRef = useRef(false) // 마이크 버튼을 누르고 있는 동안만 true ("확인" 대답 듣기와 구분)

  function onMicUp() {
    if (!pushingRef.current) return
    pushingRef.current = false
    speech.stopListening()
  }

  async function onMicDown() {
    if (!speech.sttSupported || busy || speech.listening) return
    setVoicePrompt(null)
    pushingRef.current = true
    const heard = await speech.startListening()
    if (!heard) {
      setVoicePrompt('잘 듣지 못했어요. 마이크 버튼을 누른 채로 다시 말씀해 주세요.')
      return
    }
    setInput(heard)
    setVoicePrompt(`"${heard}" 라고 말씀하셨나요? 맞으면 "확인"이라고 말씀해 주세요.`)
    await speech.speak(`${heard}, 라고 말씀하셨나요? 맞으면 확인이라고 말씀해 주세요.`)
    const answer = await speech.listenOnce(5000)
    if (YES.test(answer)) {
      await send(heard, 'voice')
    } else if (NO.test(answer)) {
      setInput('')
      setVoicePrompt('다시 말씀해 주세요.')
      speech.speak('다시 말씀해 주세요.')
    } else {
      setVoicePrompt('대답을 듣지 못했어요. 내용을 고치거나 보내기 버튼을 눌러 주세요.')
    }
  }

  return { onMicDown, onMicUp }
}
