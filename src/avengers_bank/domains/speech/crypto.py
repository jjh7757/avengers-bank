"""목소리 임베딩 암호화 (Fernet: AES-128-CBC + HMAC). 키는 .env의 VOICE_ENCRYPTION_KEY."""

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

from avengers_bank.core.config import get_settings
from avengers_bank.domains.speech.speaker import VoiceUnavailableException


def _fernet() -> Fernet:
    key = get_settings().voice_encryption_key
    if key is None or not key.get_secret_value():
        raise VoiceUnavailableException("서버에 목소리 암호화 키(VOICE_ENCRYPTION_KEY)가 설정되지 않았어요.")
    return Fernet(key.get_secret_value())


def encryption_configured() -> bool:
    key = get_settings().voice_encryption_key
    return key is not None and bool(key.get_secret_value())


def encrypt_embedding(vector: np.ndarray) -> bytes:
    return _fernet().encrypt(vector.astype(np.float32).tobytes())


def decrypt_embedding(token: bytes) -> np.ndarray:
    try:
        return np.frombuffer(_fernet().decrypt(token), dtype=np.float32)
    except InvalidToken:
        raise VoiceUnavailableException("등록된 목소리를 읽을 수 없어요. 목소리를 다시 등록해 주세요.") from None
