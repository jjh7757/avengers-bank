import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_ed25519_key(value: str) -> bool:
    """raw 32바이트의 표준 base64(44자)인지 (SPEC 2.2). 개인키·공개키 공통."""
    try:
        return len(value) == 44 and len(base64.b64decode(value.encode("ascii"), validate=True)) == 32
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return False


class Settings(BaseSettings):
    database_url: str = Field(min_length=1)
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = Field(default=15, gt=0)  # access 토큰은 짧게. 만료되면 refresh 쿠키로 새로 받는다
    refresh_token_days: int = Field(default=14, gt=0)  # 로그인 유지 기간 (쓸 때마다 새 토큰으로 바뀐다)
    # refresh 쿠키의 Secure 속성. HTTPS 운영에서는 꼭 켠다. 브라우저는 http://localhost도 안전한 곳으로 본다
    refresh_cookie_secure: bool = True
    # 방금 바꾼 refresh 토큰이 이 시간 안에 다시 오면 탈취가 아니라 탭 여러 개의 동시 갱신으로 본다
    refresh_reuse_grace_seconds: int = Field(default=20, ge=0)
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
    # 부인방지 (SPEC 2.3·2.5·2.6, docs/INTERBANK.md "부인방지(Ed25519)").
    # 우리 Ed25519 개인키(raw 32바이트 base64). 있으면 /interbank/* 응답에 모드와 상관없이 응답 서명을 붙인다.
    # 없으면 Ed25519로 요청 서명·응답 서명을 못 한다. 만들기: python -m avengers_bank.domains.interbank.keys generate
    interbank_signing_key: SecretStr | None = None
    # 허브 공개키. GET /v1/hub-key로 받아 허브 관리자가 따로 알려 준 지문과 맞춘 뒤 넣는다 (keys hub-key)
    hub_public_key: str | None = None
    # 허브 관리자가 우리에게 정한 서명 모드와 같게 둔다 (SPEC 2절 표).
    #   hmac    보낼 때 HMAC, 받을 때 HMAC만, 허브 응답 서명은 보지 않는다 (예전과 같다)
    #   both    보낼 때 Ed25519(키가 있으면), 받을 때 HMAC·Ed25519 둘 다, 허브 응답 서명은 있으면 검증해 기록만
    #   ed25519 보낼 때 Ed25519, 받을 때 Ed25519만, 허브 응답 서명 필수 (없거나 틀리면 "응답 없음")
    interbank_signature_mode: Literal["hmac", "both", "ed25519"] = "hmac"
    interbank_confirm_interval_seconds: float = Field(default=30, gt=0)  # 처리 중(PENDING) 타행 이체 확인 간격
    # 허브 정산 대사(SPEC 10.6) 간격. 시작 뒤 첫 대사는 지연만큼 기다렸다 한 번 돈다 (꺼져 있던 동안 놓친 run).
    # 지연은 앱이 뜨고 처리 중 이체 확인이 한 번 돌 틈을 준다 (그래야 "확인 중"이 덜 난다)
    interbank_settlement_sync_interval_seconds: float = Field(default=3600, gt=0)
    interbank_settlement_sync_startup_delay_seconds: float = Field(default=60, ge=0)
    # 본인 명의 계좌 조회(SPEC 9절)의 가상 CI 키. 허브 관리자가 secret과 같은 경로로 준다. 없으면 이 기능만 꺼진다
    ci_key: SecretStr | None = None

    @property
    def interbank_enabled(self) -> bool:
        return bool(self.hub_url and self.hub_api_key and self.hub_secret)

    @model_validator(mode="after")
    def _check_signature_keys(self) -> "Settings":
        """키 형식이 틀리면 응답마다 500이 나므로 시작할 때 막는다. ed25519 모드인데 키가 없으면
        허브가 우리 요청·응답을 모두 거절하므로(이체가 PENDING으로 쌓인다) 경고 대신 시작하지 않는다."""
        # .env에 빈 값(`INTERBANK_SIGNING_KEY=`)으로 두면 없는 것으로 본다
        key = self.interbank_signing_key.get_secret_value().strip() if self.interbank_signing_key else ""
        self.interbank_signing_key = SecretStr(key) if key else None
        self.hub_public_key = (self.hub_public_key or "").strip() or None
        if key and not _is_ed25519_key(key):
            raise ValueError("INTERBANK_SIGNING_KEY는 Ed25519 개인키 raw 32바이트의 base64(44자)여야 합니다")
        if self.hub_public_key and not _is_ed25519_key(self.hub_public_key):
            raise ValueError("HUB_PUBLIC_KEY는 Ed25519 공개키 raw 32바이트의 base64(44자)여야 합니다")
        if self.interbank_signature_mode == "ed25519" and not (key and self.hub_public_key):
            raise ValueError("INTERBANK_SIGNATURE_MODE=ed25519에는 INTERBANK_SIGNING_KEY와 HUB_PUBLIC_KEY가 모두 필요합니다")
        return self

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
