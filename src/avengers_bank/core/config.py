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
    gemini_embedding_model: str = "gemini-embedding-001"  # 약관·FAQ 검색 (knowledge MCP 서버)
    confirmation_expire_minutes: int = Field(default=5, gt=0)  # 이체 확인 카드 유효 시간
    # 음성 승인 (화자 인증). 키가 없으면 목소리 등록·음성 승인을 쓸 수 없고 버튼 승인만 된다
    voice_encryption_key: SecretStr | None = None  # Fernet 키 (목소리 특징 암호화)
    # 등록 목소리와의 코사인 유사도 기준. 합성 음성으로 잰 임시값이다 (docs/VOICE_AUTH.md).
    # 실제 사람 목소리로는 보정 전 → 팀원 녹음으로 scripts/voice_calibration.py를 돌려 정한다
    voice_similarity_threshold: float = Field(default=0.45, ge=0, le=1)
    voice_max_attempts: int = Field(default=2, gt=0)  # 카드 하나당 음성 승인 시도 횟수
    # 시연 모드: /demo/clock으로 업무 시각을 옮길 수 있다 (심야 이체 재현). 로그인 없이 바뀌므로 발표용 로컬에서만 켠다
    demo_mode: bool = False
    # 다른 은행 이체: ClearingHub 중계 서버 (clearing-hub 저장소 docs/SPEC.md). 셋 다 있어야 켜진다
    bank_code: str = Field(default="901", pattern=r"^\d{3}$")  # 허브가 배정한 우리 은행 코드
    hub_url: str | None = None  # 예: https://hub.example.com (끝에 /v1 없이)
    hub_api_key: SecretStr | None = None
    hub_secret: SecretStr | None = None  # 서명 비밀키. 허브 → 우리 요청 검증에도 쓴다
    hub_timeout_seconds: float = Field(default=10, gt=0)
    interbank_confirm_interval_seconds: float = Field(default=30, gt=0)  # 처리 중(PENDING) 타행 이체 확인 간격
    # 본인 명의 계좌 조회(SPEC 9절)의 가상 CI 키. 허브 관리자가 secret과 같은 경로로 준다. 없으면 이 기능만 꺼진다
    ci_key: SecretStr | None = None

    @property
    def interbank_enabled(self) -> bool:
        return bool(self.hub_url and self.hub_api_key and self.hub_secret)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
