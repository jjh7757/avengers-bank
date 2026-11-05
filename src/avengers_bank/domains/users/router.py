from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.exceptions import UnauthorizedException
from avengers_bank.core.rate_limit import login_failures, login_failures_by_ip
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.core.security import REFRESH_COOKIE
from avengers_bank.domains.users.schemas import (
    PinUpdate,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from avengers_bank.domains.users.service import user_service

router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(422))


@router.post(
    "/signup",
    response_model=SuccessResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409),
)
async def signup(data: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await user_service.signup(db, data)
    return SuccessResponse[UserResponse](data=user, message="회원가입이 완료되었습니다.")


def _set_refresh_cookie(response: Response, token: str) -> None:
    """httpOnly라 자바스크립트가 읽지 못한다(XSS로 훔칠 수 없음). SameSite=Strict라 다른 사이트에서 보내지 않는다."""
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post(
    "/login",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401, 429),
)
async def login(
    data: UserLogin, db: Annotated[AsyncSession, Depends(get_db)], request: Request, response: Response
):
    """access 토큰은 응답 본문으로, refresh 토큰은 httpOnly 쿠키(`ab_refresh`)로 준다.
    같은 아이디로 10분에 5번 틀리면 429 `TOO_MANY_LOGIN_ATTEMPTS`."""
    id_key = data.login_id.strip().lower()
    ip_key = request.client.host if request.client else "unknown"
    login_failures.check(id_key)
    login_failures_by_ip.check(ip_key)
    try:
        access_token, refresh_token = await user_service.login(db, data)
    except UnauthorizedException:
        login_failures.record(id_key)
        login_failures_by_ip.record(ip_key)
        raise
    login_failures.reset(id_key)
    _set_refresh_cookie(response, refresh_token)
    return SuccessResponse[TokenResponse](data=TokenResponse(access_token=access_token))


@router.post(
    "/refresh",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401),
)
async def refresh(
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
    ab_refresh: Annotated[str | None, Cookie(include_in_schema=False)] = None,
):
    """refresh 쿠키로 새 access 토큰을 받는다. 쿠키도 새 값으로 바뀐다(회전).
    이미 쓴 refresh 토큰이 다시 오면 401 `REFRESH_TOKEN_REUSED`와 함께 그 사용자의 모든 로그인을 끊는다."""
    try:
        access_token, refresh_token = await user_service.refresh(db, ab_refresh)
    except UnauthorizedException:
        response.delete_cookie(REFRESH_COOKIE, path="/")
        raise
    _set_refresh_cookie(response, refresh_token)
    return SuccessResponse[TokenResponse](data=TokenResponse(access_token=access_token))


@router.post("/logout", response_model=SuccessResponse[None])
async def logout(
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
    ab_refresh: Annotated[str | None, Cookie(include_in_schema=False)] = None,
):
    """이 기기의 refresh 토큰을 폐기하고 쿠키를 지운다. access 토큰은 짧게(15분) 살아 있다가 끝난다."""
    await user_service.logout(db, ab_refresh)
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return SuccessResponse[None](data=None, message="로그아웃했습니다.")


@router.get(
    "/me", response_model=SuccessResponse[UserResponse], responses=error_responses(401)
)
async def get_me(current_user: Annotated[UserResponse, Depends(get_current_user)]):
    return SuccessResponse[UserResponse](data=current_user)


@router.put(
    "/me/pin",
    response_model=SuccessResponse[UserResponse],
    responses=error_responses(401),
)
async def set_pin(
    data: PinUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_user)],
):
    user = await user_service.set_pin(db, current_user.user_id, data)
    return SuccessResponse[UserResponse](data=user, message="이체 PIN이 등록되었습니다.")


@router.patch(
    "/me",
    response_model=SuccessResponse[UserResponse],
    responses=error_responses(400, 401),
)
async def update_me(
    data: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserResponse, Depends(get_current_user)],
):
    user = await user_service.update_me(db, current_user.user_id, data)
    return SuccessResponse[UserResponse](data=user, message="내 정보가 수정되었습니다.")
