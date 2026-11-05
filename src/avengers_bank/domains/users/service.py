from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.clock import real_now_utc
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import (
    BadRequestException,
    ConflictException,
    UnauthorizedException,
)
from avengers_bank.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from avengers_bank.domains.users.ci import ci_of
from avengers_bank.domains.users.models import RefreshToken, User


def _aware(value: datetime) -> datetime:
    """SQLite는 시간대 없이 돌려주므로 UTC로 맞춘다 (PostgreSQL은 그대로)."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import PinUpdate, UserCreate, UserLogin, UserUpdate


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
                birth_date=data.birth_date,
                ci=ci_of(data.name, data.birth_date, data.phone),
            )
            await user_repository.save(db, user)
            await db.refresh(user)

        return user

    async def login(self, db: AsyncSession, data: UserLogin) -> tuple[str, str]:
        """(access 토큰, refresh 토큰). refresh는 라우터가 httpOnly 쿠키로 내려 준다."""
        async with db.begin():
            user = await user_repository.find_by_login_id(db, data.login_id)
            if user is None or not await run_in_threadpool(
                verify_password, data.password, user.hashed_password
            ):
                raise UnauthorizedException(
                    message="아이디 또는 비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS"
                )

            user.previous_login_at = user.last_login_at
            user.last_login_at = real_now_utc()
            refresh_token = self._issue_refresh_token(db, user.user_id)
            user_id = user.user_id

        return create_access_token(user_id), refresh_token

    def _issue_refresh_token(self, db: AsyncSession, user_id: int) -> str:
        token = new_refresh_token()
        db.add(RefreshToken(
            token_hash=hash_refresh_token(token),
            user_id=user_id,
            expires_at=real_now_utc() + timedelta(days=get_settings().refresh_token_days),
        ))
        return token

    async def refresh(self, db: AsyncSession, token: str | None) -> tuple[str, str]:
        """refresh 토큰을 새것으로 바꾸고(회전) 새 access 토큰을 준다.
        이미 바꾼(폐기된) 토큰이 다시 오면 누가 훔쳐 쓴 것으로 보고 그 사용자의 refresh 토큰을 모두 끊는다."""
        if not token:
            raise UnauthorizedException(message="다시 로그인해 주세요.", code="REFRESH_TOKEN_REQUIRED")
        reused = False
        async with db.begin():
            row = await db.get(RefreshToken, hash_refresh_token(token), with_for_update=True)
            now = real_now_utc()
            if row is None or _aware(row.expires_at) <= now:
                raise UnauthorizedException(message="로그인이 만료되었어요. 다시 로그인해 주세요.", code="INVALID_REFRESH_TOKEN")
            grace = timedelta(seconds=get_settings().refresh_reuse_grace_seconds)
            if row.revoke_reason == "rotated" and now - _aware(row.revoked_at) <= grace:
                # 탭 두 개가 거의 동시에 갱신한 경우: 탈취가 아니라 경쟁이다. 새 토큰을 하나 더 준다
                new_token = self._issue_refresh_token(db, row.user_id)
                user_id = row.user_id
            elif row.revoked_at is not None:
                reused = True
                await db.execute(
                    update(RefreshToken)
                    .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=now, revoke_reason="reuse")
                )
            else:
                row.revoked_at, row.revoke_reason = now, "rotated"
                new_token = self._issue_refresh_token(db, row.user_id)
                user_id = row.user_id
        if reused:  # 위 트랜잭션(모두 끊기)을 커밋한 뒤에 거절한다
            raise UnauthorizedException(
                message="보안을 위해 모든 기기에서 로그아웃했어요. 다시 로그인해 주세요.", code="REFRESH_TOKEN_REUSED"
            )
        return create_access_token(user_id), new_token

    async def logout(self, db: AsyncSession, token: str | None) -> None:
        if not token:
            return
        async with db.begin():
            row = await db.get(RefreshToken, hash_refresh_token(token))
            if row is not None and row.revoked_at is None:
                row.revoked_at, row.revoke_reason = real_now_utc(), "logout"

    async def get_current_user(self, db: AsyncSession, token: str) -> User:
        user_id = decode_access_token(token)
        user = await user_repository.find_by_id(db, user_id)
        if user is None:
            raise UnauthorizedException(
                message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
            )
        return user

    async def set_pin(self, db: AsyncSession, user_id: int, data: PinUpdate) -> User:
        async with db.begin():
            user = await user_repository.find_by_id(db, user_id)
            if user is None or not await run_in_threadpool(
                verify_password, data.password, user.hashed_password
            ):
                raise UnauthorizedException(
                    message="비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS"
                )
            user.hashed_pin = await run_in_threadpool(hash_password, data.pin)
            await db.flush()
        return user

    async def verify_pin(self, user: User, pin: str) -> bool:
        """transfers가 FDS MEDIUM 판정 때 쓴다. PIN 미등록이면 False."""
        if user.hashed_pin is None:
            return False
        return await run_in_threadpool(verify_password, pin, user.hashed_pin)

    async def update_me(self, db: AsyncSession, user_id: int, data: UserUpdate) -> User:
        changes = data.model_dump(exclude_unset=True)
        async with db.begin():
            user = await user_repository.find_by_id(db, user_id)
            if user is None:
                raise UnauthorizedException(
                    message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
                )
            for field in ("name", "phone"):
                if field in changes and changes[field] is None:
                    raise BadRequestException(
                        code="REQUIRED_FIELD", message="이름과 전화번호는 비울 수 없습니다."
                    )
            for field, value in changes.items():
                setattr(user, field, value)
            user.ci = ci_of(user.name, user.birth_date, user.phone)  # 이름·휴대폰·생년월일이 바뀌면 CI도 바뀐다
            await db.flush()
        return user


user_service = UserService()
