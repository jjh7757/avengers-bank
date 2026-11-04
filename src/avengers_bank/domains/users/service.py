from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.exceptions import ConflictException, UnauthorizedException
from avengers_bank.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import UserCreate, UserLogin


class UserService:
    async def signup(self, db: AsyncSession, data: UserCreate) -> User:
        hashed_password = await run_in_threadpool(hash_password, data.password)

        async with db.begin():
            if await user_repository.find_by_login_id(db, data.login_id) is not None:
                raise ConflictException(
                    code="LOGIN_ID_ALREADY_EXISTS",
                    message="이미 사용 중인 아이디입니다.",
                )
            user = User(
                login_id=data.login_id,
                hashed_password=hashed_password,
                name=data.name,
                nick_name=data.nick_name,
                phone=data.phone,
            )
            await user_repository.save(db, user)
            await db.refresh(user)

        return user

    async def login(self, db: AsyncSession, data: UserLogin) -> str:
        async with db.begin():
            user = await user_repository.find_by_login_id(db, data.login_id)
            if user is None or not await run_in_threadpool(
                verify_password, data.password, user.hashed_password
            ):
                raise UnauthorizedException(
                    message="아이디 또는 비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS"
                )

            user_id = user.user_id

        return create_access_token(user_id)

    async def get_current_user(self, db: AsyncSession, token: str) -> User:
        user_id = decode_access_token(token)
        user = await user_repository.find_by_id(db, user_id)
        if user is None:
            raise UnauthorizedException(
                message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
            )
        return user

    # TODO: PATCH /users/me — 이름, 닉네임, 전화번호 수정


user_service = UserService()
