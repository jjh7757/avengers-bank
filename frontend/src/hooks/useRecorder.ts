/** MediaRecorder 녹음 → 16kHz WAV. 목소리 등록과 음성 승인에 쓴다. */
import { useCallback, useRef, useState } from 'react'

import { toWav16k } from '../lib/wav'

export function useRecorder() {
  const supported = typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices?.getUserMedia
  const [recording, setRecording] = useState(false)
  const stopRef = useRef<(() => void) | null>(null)

  /** 녹음을 시작한다. stop()을 부르거나 maxMs가 지나면 끝나고 WAV를 돌려준다. */
  const record = useCallback(
    async (maxMs = 8000): Promise<Blob> => {
      if (!supported) throw new Error('이 브라우저는 녹음을 지원하지 않아요.')
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      const recorder = new MediaRecorder(stream)
      const chunks: Blob[] = []
      recorder.ondataavailable = (event) => chunks.push(event.data)
      const done = new Promise<Blob>((resolve, reject) => {
        recorder.onstop = () => {
          stream.getTracks().forEach((track) => track.stop())
          setRecording(false)
          stopRef.current = null
          toWav16k(new Blob(chunks, { type: recorder.mimeType })).then(resolve, reject)
        }
      })
      const timer = window.setTimeout(() => recorder.state === 'recording' && recorder.stop(), maxMs)
      stopRef.current = () => {
        window.clearTimeout(timer)
        if (recorder.state === 'recording') recorder.stop()
      }
      recorder.start()
      setRecording(true)
      return done
    },
    [supported],
  )

  const stop = useCallback(() => stopRef.current?.(), [])

  return { supported, recording, record, stop }
}
