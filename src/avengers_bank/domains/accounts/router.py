from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.schemas import (
    AccountDetailResponse,
    AccountHistoryResponse,
    AccountSummaryResponse,
    AccountType,
    AccountUpdate,
    CheckingAccountCreate,
    DepositAccountCreate,
    SavingsAccountCreate,
)
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(
    prefix="/accounts", tags=["accounts"], responses=error_responses(401, 422)
)

Db = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.get("", response_model=SuccessResponse[list[AccountSummaryResponse]])
async def get_my_accounts(db: Db, current_user: CurrentUser):
    accounts = await account_service.get_my_accounts(db, current_user)
    return SuccessResponse[list[AccountSummaryResponse]](data=accounts)


@router.post(
    "/checking",
    response_model=SuccessResponse[AccountDetailResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def open_checking(data: CheckingAccountCreate, db: Db, current_user: CurrentUser):
    account = await account_service.open_checking(db, data, current_user)
    return SuccessResponse[AccountDetailResponse](data=account, message="입출금 계좌가 개설되었습니다.")


@router.post(
    "/deposit",
    response_model=SuccessResponse[AccountDetailResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def open_deposit(data: DepositAccountCreate, db: Db, current_user: CurrentUser):
    account = await account_service.open_deposit(db, data, current_user)
    return SuccessResponse[AccountDetailResponse](data=account, message="예금 계좌가 개설되었습니다.")


@router.post(
    "/savings",
    response_model=SuccessResponse[AccountDetailResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def open_savings(data: SavingsAccountCreate, db: Db, current_user: CurrentUser):
    account = await account_service.open_savings(db, data, current_user)
    return SuccessResponse[AccountDetailResponse](data=account, message="적금 계좌가 개설되었습니다.")


@router.get(
    "/{account_type}/{account_id}",
    response_model=SuccessResponse[AccountDetailResponse],
    responses=error_responses(403, 404),
)
async def get_account(
    account_type: AccountType, account_id: int, db: Db, current_user: CurrentUser
):
    account = await account_service.get_account(db, account_type, account_id, current_user)
    return SuccessResponse[AccountDetailResponse](data=account)


@router.get(
    "/{account_type}/{account_id}/histories",
    response_model=SuccessResponse[list[AccountHistoryResponse]],
    responses=error_responses(403, 404),
)
async def get_histories(
    account_type: AccountType, account_id: int, db: Db, current_user: CurrentUser
):
    histories = await account_service.get_histories(db, account_type, account_id, current_user)
    return SuccessResponse[list[AccountHistoryResponse]](data=histories)


@router.patch(
    "/{account_type}/{account_id}",
    response_model=SuccessResponse[AccountDetailResponse],
    responses=error_responses(400, 403, 404),
)
async def update_account(
    account_type: AccountType,
    account_id: int,
    data: AccountUpdate,
    db: Db,
    current_user: CurrentUser,
):
    """보낸 필드만 바꾼다. 이체 한도를 **높일 때는** `pin`이 필요하다 (`400 PIN_NOT_SET` / `PIN_REQUIRED` / `INVALID_PIN`)."""
    account = await account_service.update_account(db, account_type, account_id, data, current_user)
    return SuccessResponse[AccountDetailResponse](data=account, message="계좌 정보가 변경되었습니다.")
