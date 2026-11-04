from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.transfers.schemas import (
    DepositPaymentCreate,
    SavingsPaymentCreate,
    TransferCreate,
    TransferResponse,
)
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(
    prefix="/transfers",
    tags=["transfers"],
    responses=error_responses(400, 401, 403, 404, 422),
)

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.post("", response_model=SuccessResponse[TransferResponse])
async def transfer(data: TransferCreate, db: Db, current_user: CurrentUser, request: Request):
    """FDS 판정에 따라 400 `FDS_BLOCKED`, `ADDITIONAL_AUTH_REQUIRED`(PIN을 넣어 다시 요청), `INVALID_PIN`이
    나갈 수 있다. 이때 `error.extra`에 규칙 이름, ML 점수, 주요 요인, 경고 문구가 들어 있다."""
    client_ip = request.client.host if request.client else None
    result = await transfer_service.transfer(db, data, current_user, client_ip)
    return SuccessResponse[TransferResponse](data=result, message="이체가 완료되었습니다.")


@router.post("/savings", response_model=SuccessResponse[TransferResponse])
async def pay_savings(data: SavingsPaymentCreate, db: Db, current_user: CurrentUser):
    result = await transfer_service.pay_savings(db, data, current_user)
    return SuccessResponse[TransferResponse](data=result, message="적금 납입이 완료되었습니다.")


@router.post("/deposit", response_model=SuccessResponse[TransferResponse])
async def pay_deposit(data: DepositPaymentCreate, db: Db, current_user: CurrentUser):
    result = await transfer_service.pay_deposit(db, data, current_user)
    return SuccessResponse[TransferResponse](data=result, message="예금 입금이 완료되었습니다.")
