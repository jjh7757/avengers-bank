from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
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


@router.post(
    "/login",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401),
)
async def login(
    data: UserLogin, db: Annotated[AsyncSession, Depends(get_db)], response: Response
):
    access_token = await user_service.login(db, data)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SuccessResponse[TokenResponse](data=TokenResponse(access_token=access_token))


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
