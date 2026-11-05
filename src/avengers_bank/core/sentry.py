"""선택 사항: Sentry 오류 수집. SENTRY_DSN이 없으면 아무것도 하지 않는다 (sentry_sdk도 import하지 않는다).

- SENTRY_DSN: Sentry 프로젝트 DSN. 비우면 꺼짐
- SENTRY_ENVIRONMENT: 기본 production
- SENTRY_TRACES_SAMPLE_RATE: 성능 추적 비율 0~1 (기본 0, 오류만 보낸다)

은행 서비스라 개인정보(요청 본문·쿠키·IP)는 보내지 않는다 (send_default_pii=False).
보낸 오류에는 request_id 태그를 붙여 서버 로그와 이어 볼 수 있게 한다.
"""

import logging
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from avengers_bank.core.logging import get_request_id

logger = logging.getLogger(__name__)


class SentrySettings(BaseSettings):
    sentry_dsn: SecretStr | None = None
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0, le=1)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_sentry_settings() -> SentrySettings:
    return SentrySettings()


def _tag_request_id(event, hint):  # noqa: ANN001 (sentry 콜백 시그니처)
    request_id = get_request_id()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def init_sentry() -> bool:
    """DSN이 있으면 Sentry를 켠다. 켰으면 True."""
    settings = get_sentry_settings()
    dsn = settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else ""
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:  # 의존성은 pyproject에 있지만, 빠진 환경에서도 앱은 떠야 한다
        logger.warning("SENTRY_DSN이 있지만 sentry-sdk가 설치되지 않아 오류 수집을 끕니다.")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=_tag_request_id,
    )
    logger.info("Sentry 오류 수집을 켰습니다 (environment=%s).", settings.sentry_environment)
    return True
