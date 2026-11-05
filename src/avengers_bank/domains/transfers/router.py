from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import NotFoundException
from avengers_bank.domains.interbank import service as interbank_service
from avengers_bank.domains.transfers.schemas import (
    DepositPaymentCreate,
    HolderInquiry,
    HolderInquiryResponse,
    InterbankBank,
    InterbankTransferResponse,
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
    message = "이체가 완료되었습니다." if result.status == "COMPLETED" else "받는 은행에서 확인 중입니다. 잠시 후 결과를 알려 드려요."
    return SuccessResponse[TransferResponse](data=result, message=message)


@router.post("/inquiry", response_model=SuccessResponse[HolderInquiryResponse])
async def inquiry(data: HolderInquiry, db: Db, current_user: CurrentUser):
    """받는 분 이름 확인 (이체 화면의 확인 단계). 다른 은행이면 ClearingHub에 묻는다. 돈은 움직이지 않는다."""
    if interbank_service.is_external(data.to_bank):
        bank_name = await interbank_service.bank_name(data.to_bank)
        name = await interbank_service.inquiry(data.to_bank, data.to_account_num)
    else:
        name, bank_name = await interbank_service.holder_name_of(db, data.to_account_num), "AvengersBank"
        if name is None:
            raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="받는 계좌를 찾을 수 없습니다.")
    return SuccessResponse[HolderInquiryResponse](data=HolderInquiryResponse(
        to_bank=data.to_bank or get_settings().bank_code, bank_name=bank_name,
        to_account_num=data.to_account_num, holder_name=name,
    ))


@router.get("/banks", response_model=SuccessResponse[list[InterbankBank]])
async def list_banks(current_user: CurrentUser):
    """다른 은행 이체로 보낼 수 있는 은행 (ClearingHub 참가 은행, 우리 은행 제외). 허브 설정이 없으면 503."""
    banks = await interbank_service.list_banks()
    return SuccessResponse[list[InterbankBank]](data=[InterbankBank(**b) for b in banks])


@router.get("/interbank", response_model=SuccessResponse[list[InterbankTransferResponse]])
async def list_interbank_transfers(db: Db, current_user: CurrentUser):
    """내 타행 이체와 상태 (PENDING: 받는 은행 확인 중, COMPLETED, FAILED: 출금 되돌림)"""
    async with db.begin():
        rows = await interbank_service.list_my_transfers(db, current_user.user_id)
    return SuccessResponse[list[InterbankTransferResponse]](
        data=[InterbankTransferResponse.model_validate(r, from_attributes=True) for r in rows]
    )


@router.post("/savings", response_model=SuccessResponse[TransferResponse])
async def pay_savings(data: SavingsPaymentCreate, db: Db, current_user: CurrentUser):
    result = await transfer_service.pay_savings(db, data, current_user)
    return SuccessResponse[TransferResponse](data=result, message="적금 납입이 완료되었습니다.")


@router.post("/deposit", response_model=SuccessResponse[TransferResponse])
async def pay_deposit(data: DepositPaymentCreate, db: Db, current_user: CurrentUser):
    result = await transfer_service.pay_deposit(db, data, current_user)
    return SuccessResponse[TransferResponse](data=result, message="예금 입금이 완료되었습니다.")
