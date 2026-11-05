import { Delete, Shuffle } from 'lucide-react'
import { useState, type KeyboardEvent } from 'react'

/** 0~9를 무작위로 섞는다. 누른 위치로 PIN을 짐작할 수 없게(어깨 너머 보기, 화면 녹화) 한다 */
function shuffledDigits(): string[] {
  const digits = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']
  const random = new Uint32Array(digits.length)
  crypto.getRandomValues(random)
  for (let i = digits.length - 1; i > 0; i--) {
    const j = random[i] % (i + 1)
    ;[digits[i], digits[j]] = [digits[j], digits[i]]
  }
  return digits
}

/**
 * 보안 키패드: 숫자 배열이 매번 바뀌고, 입력한 숫자는 점으로만 보인다.
 * 물리 키보드의 숫자·Backspace도 받는다 (키패드에 초점이 있을 때).
 */
export default function PinPad({
  value,
  onChange,
  length = 6,
  label = '이체 PIN',
  disabled = false,
  autoFocus = false,
}: {
  value: string
  onChange: (value: string) => void
  length?: number
  label?: string
  disabled?: boolean
  autoFocus?: boolean
}) {
  const [digits, setDigits] = useState(shuffledDigits)

  function press(digit: string) {
    if (disabled || value.length >= length) return
    onChange(value + digit)
  }

  function backspace() {
    if (!disabled) onChange(value.slice(0, -1))
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (/^\d$/.test(event.key)) {
      event.preventDefault()
      press(event.key)
    } else if (event.key === 'Backspace') {
      event.preventDefault()
      backspace()
    }
  }

  return (
    <div
      className={`pinpad ${disabled ? 'disabled' : ''}`}
      role="group"
      aria-label={`${label} 입력 (보안 키패드)`}
      tabIndex={0}
      onKeyDown={onKeyDown}
      autoFocus={autoFocus}
    >
      <p className="pinpad-label">{label}</p>
      <div className="pinpad-dots" aria-live="polite" aria-label={`${value.length}자리 입력됨`}>
        {Array.from({ length }, (_, i) => (
          <span key={i} className={`pinpad-dot ${i < value.length ? 'filled' : ''}`} />
        ))}
      </div>
      <div className="pinpad-keys">
        {digits.slice(0, 9).map((d) => (
          <button key={d} type="button" className="pinpad-key" onClick={() => press(d)} disabled={disabled} aria-label={d}>
            {d}
          </button>
        ))}
        <button
          type="button"
          className="pinpad-key fn"
          onClick={() => setDigits(shuffledDigits())}
          disabled={disabled}
          aria-label="숫자 배열 다시 섞기"
          title="숫자 배열 다시 섞기"
        >
          <Shuffle size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="pinpad-key"
          onClick={() => press(digits[9])}
          disabled={disabled}
          aria-label={digits[9]}
        >
          {digits[9]}
        </button>
        <button type="button" className="pinpad-key fn" onClick={backspace} disabled={disabled} aria-label="한 자리 지우기">
          <Delete size={22} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}
