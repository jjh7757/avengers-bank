"""이체 확인 카드의 승인 토큰.

에이전트는 이체를 실행하지 않는다. prepare_transfer가 확인 카드와 함께 이 토큰을 만들고,
사용자가 승인 버튼을 누르면 프론트가 카드 내용 그대로 POST /transfers에 토큰을 실어 보낸다.
transfers.service는 토큰 서명·만료·내용 일치를 검사하고, 세션에 저장된 jti와 비교해 한 번만 쓰게 한다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from avengers_bank.core.clock import now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import BadRequestException
from avengers_bank.core.security import ALGORITHM

TOKEN_TYPE = "transfer_confirmation"


@dataclass(frozen=True)
class Confirmation:
    jti: str
    user_id: int
    session_id: str
    from_checking_account_id: int
    to_account_num: str
    amount: int
    voice_challenge: str | None  # 음성 승인 때 말해야 하는 무작위 숫자 (목소리 미등록이면 None)


def create_confirmation_token(
    *,
    user_id: int,
    session_id: str,
    from_checking_account_id: int,
    to_account_num: str,
    amount: int,
    voice_challenge: str | None = None,
) -> tuple[str, str, datetime]:
    """(토큰, jti, 만료 시각)"""
    settings = get_settings()
    now = now_utc()
    expires_at = now + timedelta(minutes=settings.confirmation_expire_minutes)
    jti = uuid.uuid4().hex
    payload = {
        "typ": TOKEN_TYPE,
        "jti": jti,
        "sub": str(user_id),
        "sid": session_id,
        "from": from_checking_account_id,
        "to": to_account_num,
        "amt": amount,
        "vc": voice_challenge,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_confirmation_token(token: str) -> Confirmation:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret_key.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["typ", "jti", "sub", "sid", "from", "to", "amt", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise BadRequestException(
            code="CONFIRMATION_EXPIRED", message="확인 시간이 지났어요. 다시 요청해 주세요."
        ) from None
    except jwt.InvalidTokenError:
        raise BadRequestException(
            code="INVALID_CONFIRMATION", message="이체 확인 정보가 올바르지 않습니다."
        ) from None
    if payload["typ"] != TOKEN_TYPE:
        raise BadRequestException(code="INVALID_CONFIRMATION", message="이체 확인 정보가 올바르지 않습니다.")
    return Confirmation(
        jti=payload["jti"],
        user_id=int(payload["sub"]),
        session_id=payload["sid"],
        from_checking_account_id=payload["from"],
        to_account_num=payload["to"],
        amount=payload["amt"],
        voice_challenge=payload.get("vc"),
    )
