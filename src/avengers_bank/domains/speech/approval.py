"""음성 승인 토큰: 숫자·목소리 확인을 통과한 확인 카드(jti)에만 2분 동안 유효하다."""

from datetime import timedelta

import jwt

from avengers_bank.core.clock import real_now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import BadRequestException
from avengers_bank.core.security import ALGORITHM

TOKEN_TYPE = "voice_approval"
EXPIRE = timedelta(minutes=2)


def create_voice_approval_token(user_id: int, confirmation_jti: str) -> str:
    now = real_now_utc()  # JWT 만료는 실제 시각 기준
    payload = {"typ": TOKEN_TYPE, "sub": str(user_id), "cjti": confirmation_jti, "iat": now, "exp": now + EXPIRE}
    return jwt.encode(payload, get_settings().jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)


def verify_voice_approval_token(token: str, *, user_id: int, confirmation_jti: str) -> None:
    try:
        payload = jwt.decode(
            token, get_settings().jwt_secret_key.get_secret_value(), algorithms=[ALGORITHM],
            options={"require": ["typ", "sub", "cjti", "exp"]},
        )
    except jwt.InvalidTokenError:
        payload = None
    if payload is None or payload["typ"] != TOKEN_TYPE or payload["sub"] != str(user_id) or payload["cjti"] != confirmation_jti:
        raise BadRequestException(
            code="INVALID_VOICE_APPROVAL", message="음성 승인이 만료됐거나 올바르지 않아요. 다시 승인해 주세요."
        )
