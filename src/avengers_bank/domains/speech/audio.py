"""업로드된 녹음 읽기. 프론트가 브라우저에서 16kHz·모노·16bit WAV로 바꿔서 보낸다.
서버에 ffmpeg나 오디오 디코더가 없어도 되도록 WAV만 받는다."""

import io
import wave

import numpy as np

from avengers_bank.core.exceptions import BadRequestException

SAMPLE_RATE = 16_000
MIN_SECONDS = 0.8
MAX_SECONDS = 15
MAX_BYTES = SAMPLE_RATE * 2 * MAX_SECONDS + 1024


def invalid(message: str) -> BadRequestException:
    return BadRequestException(code="INVALID_AUDIO", message=message)


def read_wav(data: bytes) -> np.ndarray:
    """WAV 바이트 → float32 [-1, 1] 1차원 배열"""
    if len(data) > MAX_BYTES:
        raise invalid(f"녹음이 너무 길어요. {MAX_SECONDS}초 안으로 말씀해 주세요.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                raise invalid("16kHz 모노 16bit WAV만 받을 수 있어요.")
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        raise invalid("녹음 파일을 읽을 수 없어요.") from None
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768
    seconds = len(samples) / SAMPLE_RATE
    if seconds < MIN_SECONDS:
        raise invalid("녹음이 너무 짧아요. 버튼을 누르고 또박또박 말씀해 주세요.")
    if seconds > MAX_SECONDS:
        raise invalid(f"녹음이 너무 길어요. {MAX_SECONDS}초 안으로 말씀해 주세요.")
    if float(np.sqrt(np.mean(samples**2))) < 0.003:
        raise invalid("소리가 거의 들리지 않아요. 마이크 가까이에서 다시 말씀해 주세요.")
    return samples
