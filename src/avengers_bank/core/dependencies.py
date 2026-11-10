from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ForbiddenException, UnauthorizedException
from avengers_bank.domains.users.models import UserRole
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.domains.users.service import user_service

bearer_scheme = HTTPBearer(bearerFormat="JWT", auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> UserResponse:
    if credentials is None:
        raise UnauthorizedException(
            message="로그인이 필요합니다.", code="AUTHENTICATION_REQUIRED"
        )
    async with SessionLocal() as db:
        user = await user_service.get_current_user(db, credentials.credentials)
        return UserResponse.model_validate(user)


async def require_admin(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    """관리자만. 역할은 토큰에 넣지 않고 get_current_user가 매 요청 DB에서 읽은 값을 본다
    (CLI로 강등하면 이미 발급한 토큰으로도 바로 막힌다)."""
    if current_user.role != UserRole.ADMIN:
        raise ForbiddenException(message="관리자만 쓸 수 있습니다.", code="ADMIN_REQUIRED")
    return current_user
