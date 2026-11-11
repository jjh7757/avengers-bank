import base64
import binascii
from functools import lru_cache

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
    # 시연 모드: /demo/clock으로 업무 시각을 옮길 수 있다 (심야 이체 재현). 로그인 없이 바뀌므로 발표용 로컬에서만 켠다
    demo_mode: bool = False
    # 시연용 가상 입금 (POST /accounts/checking/{id}/cash-deposit). 돈을 새로 만드는 기능이라 한도를 둔다.
    # 1일 한도는 사용자별, 한국 시간 0시부터의 합계
    cash_deposit_max_amount: int = Field(default=1_000_000, gt=0)
    cash_deposit_daily_limit: int = Field(default=3_000_000, gt=0)
    # 다른 은행 이체: ClearingHub 중계 서버 (clearing-hub 저장소 docs/SPEC.md v1.0, docs/INTERBANK.md).
    # HUB_URL·HUB_API_KEY·INTERBANK_SIGNING_KEY·HUB_PUBLIC_KEY 넷 다 있어야 켜진다 (interbank_enabled)
    bank_code: str = Field(default="901", pattern=r"^\d{3}$")  # 허브가 배정한 우리 은행 코드 (셀프 등록 응답의 bank_code)
    hub_url: str | None = None  # 예: https://hub.example.com (끝에 /v1 없이)
    hub_api_key: SecretStr | None = None  # 등록 때 받은 API 키. 식별용이다 (서명 키가 아님, SPEC 2절)
    hub_timeout_seconds: float = Field(default=10, gt=0)
    # 서명은 Ed25519 하나다 (SPEC 2절). 허브는 우리 비밀을 갖지 않고 공개키만 갖는다.
    # 우리 Ed25519 개인키(raw 32바이트 base64): 허브 요청 서명과 /interbank/* 응답 서명(SPEC 2.5)에 쓴다.
    # 허브를 포함해 누구에게도 주지 않는다. 만들기: python -m avengers_bank.domains.interbank.keys generate
    interbank_signing_key: SecretStr | None = None
    # 허브 공개키: 허브 → 우리 요청과 허브 응답 서명을 검증한다. GET /v1/hub-key로 받아(keys hub-key)
    # 허브 관리자가 초대 코드와 함께 따로 알려 준 지문과 맞춘 뒤 넣는다
    hub_public_key: str | None = None
    interbank_confirm_interval_seconds: float = Field(default=30, gt=0)  # 처리 중(PENDING) 타행 이체 확인 간격
    # 허브 정산 대사(SPEC 10.6) 간격. 시작 뒤 첫 대사는 지연만큼 기다렸다 한 번 돈다 (꺼져 있던 동안 놓친 run).
    # 지연은 앱이 뜨고 처리 중 이체 확인이 한 번 돌 틈을 준다 (그래야 "확인 중"이 덜 난다)
    interbank_settlement_sync_interval_seconds: float = Field(default=3600, gt=0)
    interbank_settlement_sync_startup_delay_seconds: float = Field(default=60, ge=0)
    # 본인 명의 계좌 조회(SPEC 9절)의 가상 CI 키. 허브 관리자가 초대 코드와 같은 개별 경로로 준다 (SPEC 7절 1). 없으면 이 기능만 꺼진다
    ci_key: SecretStr | None = None

    @property
    def interbank_missing(self) -> list[str]:
        """타행 이체에 필요한데 비어 있는 설정 이름. 비어 있으면 타행 이체가 켜진다."""
        values = {"HUB_URL": self.hub_url, "HUB_API_KEY": self.hub_api_key,
                  "INTERBANK_SIGNING_KEY": self.interbank_signing_key, "HUB_PUBLIC_KEY": self.hub_public_key}
        return [name for name, value in values.items() if not value]

    @property
    def interbank_enabled(self) -> bool:
        return not self.interbank_missing

    @property
    def interbank_receive_enabled(self) -> bool:
        """허브가 부르는 /interbank/*를 받을 수 있는지: 허브 서명 검증(HUB_PUBLIC_KEY)과 응답 서명(INTERBANK_SIGNING_KEY)만
        있으면 된다. HUB_API_KEY는 셀프 등록 응답으로 받으므로, 등록 직후 허브의 ping(SPEC 3.5)은 이것만으로 통과해야 한다."""
        return bool(self.interbank_signing_key and self.hub_public_key)

    @model_validator(mode="after")
    def _check_signature_keys(self) -> "Settings":
        """키 형식이 틀리면 서명·검증마다 실패(응답마다 500, 모든 이체 PENDING)하므로 시작할 때 막는다.
        키가 없는 것은 오류가 아니다: 타행 이체만 꺼진다 (interbank_enabled, 시작 로그에 빠진 이름)."""
        # .env에 빈 값(`INTERBANK_SIGNING_KEY=`)으로 두면 없는 것으로 본다
        key = self.interbank_signing_key.get_secret_value().strip() if self.interbank_signing_key else ""
        self.interbank_signing_key = SecretStr(key) if key else None
        self.hub_public_key = (self.hub_public_key or "").strip() or None
        if key and not _is_ed25519_key(key):
            raise ValueError("INTERBANK_SIGNING_KEY는 Ed25519 개인키 raw 32바이트의 base64(44자)여야 합니다")
        if self.hub_public_key and not _is_ed25519_key(self.hub_public_key):
            raise ValueError("HUB_PUBLIC_KEY는 Ed25519 공개키 raw 32바이트의 base64(44자)여야 합니다")
        return self

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
