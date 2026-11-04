/**
 * MediaRecorder 결과(webm/opus 등)를 16kHz·모노·16bit WAV로 바꾼다.
 * 서버는 WAV만 받는다 (ffmpeg 없이 읽기 위해).
 */
const TARGET_RATE = 16_000

export async function toWav16k(recorded: Blob): Promise<Blob> {
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await recorded.arrayBuffer())
    const length = Math.ceil(decoded.duration * TARGET_RATE)
    const offline = new OfflineAudioContext(1, length, TARGET_RATE) // 채널 1개로 그리면 모노로 섞인다
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    return encodeWav(rendered.getChannelData(0), TARGET_RATE)
  } finally {
    await context.close()
  }
}

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const text = (offset: number, value: string) => [...value].forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)))
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 청크 크기
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // 모노
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 초당 바이트
  view.setUint16(32, 2, true) // 샘플당 바이트
  view.setUint16(34, 16, true) // 16bit
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((sample, i) => {
    const clipped = Math.max(-1, Math.min(1, sample))
    view.setInt16(44 + i * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true)
  })
  return new Blob([buffer], { type: 'audio/wav' })
}
