import { useCallback, useState, type FormEvent } from 'react'
import { CircleCheck } from 'lucide-react'

import { ApiError } from '../api/client'
import { voiceApi } from '../api/endpoints'
import { useLoad } from '../hooks/useLoad'
import { useRecorder } from '../hooks/useRecorder'
import { dateTime } from '../lib/format'

const SENTENCES = [
  '오늘 날씨가 참 맑고 좋네요.',
  '우리 가족은 주말마다 공원에 산책을 갑니다.',
  '은행 업무를 말로 편하게 보고 싶어요.',
]

/** 설정 > 목소리 등록. 생체정보 동의 → 문장 3개 녹음 → 비밀번호 확인 → 등록 */
export default function VoiceEnrollment() {
  const { data: profile, error: loadError, loading } = useLoad(useCallback(() => voiceApi.profile(), []))
  const [current, setCurrent] = useState(profile)
  const recorder = useRecorder()
  const [consent, setConsent] = useState(false)
  const [recordings, setRecordings] = useState<(Blob | null)[]>([null, null, null])
  const [recordingIndex, setRecordingIndex] = useState<number | null>(null)
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const shown = current ?? profile

  async function toggleRecord(index: number) {
    if (recorder.recording) {
      recorder.stop()
      return
    }
    setMessage(null)
    setRecordingIndex(index)
    try {
      const wav = await recorder.record(10_000)
      setRecordings((prev) => prev.map((r, i) => (i === index ? wav : r)))
    } catch {
      setMessage({ ok: false, text: '마이크를 쓸 수 없어요. 브라우저의 마이크 권한을 확인해 주세요.' })
    } finally {
      setRecordingIndex(null)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      setCurrent(await voiceApi.enroll(password, recordings as Blob[]))
      setRecordings([null, null, null])
      setPassword('')
      setConsent(false)
      setMessage({ ok: true, text: '목소리를 등록했어요. 이제 이체를 "확인 + 숫자"로 말해서 승인할 수 있어요.' })
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : '등록하지 못했어요.' })
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    const pw = window.prompt('목소리를 지우려면 로그인 비밀번호를 입력해 주세요.')
    if (!pw) return
    try {
      await voiceApi.remove(pw)
      setCurrent({ enrolled: false, available: shown?.available ?? false, created_at: null, updated_at: null })
      setMessage({ ok: true, text: '등록한 목소리를 지웠어요.' })
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : '지우지 못했어요.' })
    }
  }

  if (loading && !current) return <p className="muted">불러오는 중…</p>
  if (loadError) return <p className="error">{loadError}</p>
  if (!shown) return null

  return (
    <div className="voice-enroll">
      {!shown.available && (
        <p className="notice">지금 서버에서 음성 승인을 쓸 수 없어요. 이체는 승인 버튼과 PIN으로 진행돼요.</p>
      )}
      {shown.enrolled ? (
        <div className="panel">
          <p>
            <CircleCheck size={20} aria-hidden="true" className="inline-icon success" /> 목소리가 등록되어 있어요 <span className="muted small">({dateTime(shown.updated_at!)})</span>
          </p>
          <p className="small muted">이체 확인 카드에서 "확인 + 숫자"를 말하면 승인돼요. 승인 버튼으로 할 때는 PIN이 필요해요.</p>
          <div className="button-row">
            <button className="button" onClick={() => setCurrent({ ...shown, enrolled: false })}>
              다시 등록
            </button>
            <button className="button" onClick={remove}>
              목소리 지우기
            </button>
          </div>
        </div>
      ) : (
        <form className="form" onSubmit={submit}>
          <label className="consent">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>
              <strong>생체정보 수집·이용 동의</strong>
              <span className="small muted">
                {' '}
                목소리 특징(숫자 벡터)을 암호화해 이체 승인 본인 확인에만 씁니다. 녹음 원본은 저장하지 않으며, 언제든 지울 수 있어요.
                동의하지 않아도 승인 버튼으로 이체할 수 있어요.
              </span>
            </span>
          </label>
          {consent && (
            <>
              <p className="small muted">버튼을 누르고 문장을 또박또박 읽은 뒤 다시 눌러 주세요.</p>
              <ol className="sentences">
                {SENTENCES.map((sentence, i) => (
                  <li key={sentence}>
                    <span>"{sentence}"</span>
                    <button
                      type="button"
                      className={`button small ${recordingIndex === i ? 'recording' : ''}`}
                      onClick={() => toggleRecord(i)}
                      disabled={!recorder.supported || (recorder.recording && recordingIndex !== i)}
                    >
                      {recordingIndex === i ? '녹음 끝' : recordings[i] ? '다시 녹음' : '녹음'}
                    </button>
                  </li>
                ))}
              </ol>
              <label>
                로그인 비밀번호
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </label>
              <button className="button primary" disabled={busy || recordings.some((r) => !r) || !password || !shown.available}>
                {busy ? '등록 중…' : '목소리 등록'}
              </button>
            </>
          )}
        </form>
      )}
      {message && (
        <p className={message.ok ? 'success' : 'error'} role="status">
          {message.text}
        </p>
      )}
    </div>
  )
}
