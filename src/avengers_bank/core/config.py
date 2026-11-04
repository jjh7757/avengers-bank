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

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
