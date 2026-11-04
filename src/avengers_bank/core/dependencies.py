from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import UnauthorizedException
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
