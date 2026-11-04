from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(min_length=1)
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = Field(default=30, gt=0)
    db_echo: bool = False
    gemini_api_key: SecretStr | None = None
    gemini_fast_model: str = "gemini-2.5-flash"  # 매 메시지: 의도 분류·슬롯 추출 (빠른 응답)
    gemini_chat_model: str = "gemini-3.8-flash"  # 조회·상담 답변 (도구 호출)
    confirmation_expire_minutes: int = Field(default=5, gt=0)  # 이체 확인 카드 유효 시간
    # 음성 승인 (화자 인증). 키가 없으면 목소리 등록·음성 승인을 쓸 수 없고 버튼 승인만 된다
    voice_encryption_key: SecretStr | None = None  # Fernet 키 (목소리 특징 암호화)
    # 등록 목소리와의 코사인 유사도 기준. 합성 음성으로 잰 임시값이다 (docs/VOICE_AUTH.md).
    # 실제 사람 목소리로는 보정 전 → 팀원 녹음으로 scripts/voice_calibration.py를 돌려 정한다
    voice_similarity_threshold: float = Field(default=0.45, ge=0, le=1)
    voice_max_attempts: int = Field(default=2, gt=0)  # 카드 하나당 음성 승인 시도 횟수

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
